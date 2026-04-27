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
  python research.py --pair                              # First-time login to all services
"""

import sys
import os
import re
import time
import json
import base64
import socket
import asyncio
import random
import shutil
import argparse
import subprocess
import collections
from pathlib import Path
from prompts import *
from datetime import datetime

# Vision tier-2 module (shadow-eval today, tier-2 promotion per hotspot
# after telemetry proves agreement). Wrapped in try/except so a vision.py
# import error never breaks the pipeline — shadow mode is opt-in via
# DG_VISION_TIER=shadow and default-off.
try:
    import vision as _vision  # type: ignore
except Exception as _ve:
    _vision = None  # noqa: N816 — fallthrough; shadow path no-ops below.
    print(f"[vision] import failed (shadow disabled): {_ve}", flush=True)

# Windows UTF-8 fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# ── Constants ──────────────────────────────────────────────────────────────────

PROFILE_DIR = Path.home() / ".super-research" / "browser-profile"
BETA_FLAG = "computer-use-2025-11-24"
# All configurable via env vars (defaults are production-tuned)
CUA_MODEL = os.environ.get("CUA_MODEL", "claude-opus-4-7")
API_WIDTH = int(os.environ.get("CUA_SCREEN_WIDTH", "1280"))
API_HEIGHT = int(os.environ.get("CUA_SCREEN_HEIGHT", "800"))

# Polling intervals (override via env for testing with shorter waits)
POLL_PRO = int(os.environ.get("POLL_PRO", "30"))                 # seconds
# 2026-04-25: P2 round-robin completion-check cadence. Bumped from 30→120s
# to reduce bot-flag risk (rapid tab-switching at 30s intervals can look
# bot-like to ChatGPT/Gemini/Claude) and to give the BE more time to scrape
# rich state per cycle. Narration cadence is independent (Gemini Flash
# narrator runs every 6s during P1/P2 from the event ring buffer), so this
# does NOT slow down the FE phase-dropdown narration.
POLL_DEEP_RESEARCH = int(os.environ.get("POLL_DEEP_RESEARCH", "120"))  # seconds
MAX_WAIT_PRO = int(os.environ.get("MAX_WAIT_PRO", "45"))         # minutes — Phase 1
MAX_WAIT_DEEP = int(os.environ.get("MAX_WAIT_DEEP", "90"))       # minutes — Phase 2

# Per-phase wall-clock ceilings (2026-04-25). If a phase exceeds these,
# the orchestrator emits pipeline_stopped + reason="phase_timeout" and
# terminates the run. Without these caps a dead laptop or stalled CUA
# could keep the run going indefinitely (user reported a run continuing
# overnight). Override via env for E2E with shorter ceilings.
PHASE_1_MAX_MIN = int(os.environ.get("PHASE_1_MAX_MIN", "35"))   # brief gen typical 21-27m
PHASE_2_MAX_MIN = int(os.environ.get("PHASE_2_MAX_MIN", "90"))   # 3 agents in parallel
PHASE_3_UPLOAD_MAX_MIN = int(os.environ.get("PHASE_3_UPLOAD_MAX_MIN", "15"))
PHASE_3_AUDIO_MAX_MIN = int(os.environ.get("PHASE_3_AUDIO_MAX_MIN", "20"))   # observed 15-20m, gated on NotebookLM opaque audio gen
PHASE_4_MAX_MIN = int(os.environ.get("PHASE_4_MAX_MIN", "15"))   # ffmpeg + YouTube
PHASE_5_MAX_MIN = int(os.environ.get("PHASE_5_MAX_MIN", "10"))   # GDoc + email


# ── Helpers ────────────────────────────────────────────────────────────────────

def _read_user_scope_env(name: str) -> str:
    """Read a Windows User-scope env var via PowerShell. Empty string
    on non-Windows or failure. Persistent across shells — settable via
    the Account page sync (preferred) or PowerShell
    SetEnvironmentVariable(..., 'User')."""
    if sys.platform != "win32":
        return ""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             f"[System.Environment]::GetEnvironmentVariable('{name}','User')"],
            capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return ""


def get_env(name):
    """os.environ first, User-scope Windows env as fallback. Keeps the
    legacy contract for callers that just want 'whatever env has this
    name'. See resolve_api_key for CUA key resolution order, which is
    deliberately reversed."""
    val = os.environ.get(name, "")
    if not val:
        val = _read_user_scope_env(name)
    return val


def _read_firestore_api_keys() -> dict:
    """Best-effort read of users/{paired_uid}/settings/prefs → apiKeys.
    Returns dict of {gemini, anthropic, deepgram} strings (any subset),
    or empty dict if unpaired / Firestore unreachable / uid unknown.

    This is the Account page sync: the user sets keys in the web app,
    they land in Firestore, and the backend picks them up on startup
    without needing a shell env or PowerShell setup. Read-only and
    silent on failure — env fallback still works."""
    try:
        uid = load_paired_uid()
        if not uid:
            return {}
        if _firebase_db is None:
            # Firestore not initialized yet (e.g. startup path that
            # hasn't called initialize_firebase_admin). Skip quietly.
            return {}
        snap = _firebase_db.collection("users").document(uid) \
            .collection("settings").document("prefs").get()
        if not snap.exists:
            return {}
        data = snap.to_dict() or {}
        keys = data.get("apiKeys") or {}
        # Strip + filter empty values so callers can treat any present
        # key as authoritative.
        return {k: str(v).strip() for k, v in keys.items() if v and str(v).strip()}
    except Exception as e:
        log(f"[_read_firestore_api_keys] read failed (non-fatal): {e}", "WARN")
        return {}


def resolve_api_key(cli_key=None):
    """Resolve the CUA / Anthropic API key. Priority (highest first):
        1. --api-key CLI argument
        2. Firestore apiKeys.anthropic (from the web app's Account page)
        3. Windows User-scope CUA_API_KEY
        4. Windows User-scope ANTHROPIC_API_KEY
        5. os.environ CUA_API_KEY  (shell / .bashrc)
        6. os.environ ANTHROPIC_API_KEY

    Rationale: the user's intentional settings — CLI arg, web app, or
    PowerShell SetEnvironmentVariable 'User' — should always win over a
    stale shell profile that may have cached an old key. This prevents
    the 'I set a new key in PowerShell but the backend keeps using the
    old one from .bashrc' trap.

    Logs which source was chosen so mismatches are debuggable."""
    if cli_key:
        log(f"[resolve_api_key] using --api-key CLI argument", "INFO")
        return cli_key
    # 2. Firestore Account page key
    fs_keys = _read_firestore_api_keys()
    if fs_keys.get("anthropic"):
        log(f"[resolve_api_key] using apiKeys.anthropic from Firestore (Account page)", "INFO")
        return fs_keys["anthropic"]
    # 3 + 4. User-scope env (persistent)
    for var in ("CUA_API_KEY", "ANTHROPIC_API_KEY"):
        key = _read_user_scope_env(var)
        if key:
            shell_val = os.environ.get(var, "")
            if shell_val and shell_val != key:
                log(f"[resolve_api_key] {var}: Windows User-scope wins over shell env (shell had a stale value)", "INFO")
            else:
                log(f"[resolve_api_key] using {var} from Windows User-scope", "INFO")
            return key
    # 5 + 6. os.environ (shell-inherited)
    for var in ("CUA_API_KEY", "ANTHROPIC_API_KEY"):
        key = os.environ.get(var, "").strip()
        if key:
            log(f"[resolve_api_key] using {var} from shell env (no User-scope / Firestore key)", "INFO")
            return key
    return None


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


# ── Terminal colors (used by --pair for the branded UI) ──────────────────
# Detects tty + enables ANSI on Windows 10+ so colors render in cmd/powershell.
_USE_COLOR = False
try:
    if sys.stdout.isatty():
        _USE_COLOR = True
        if sys.platform == "win32":
            # Enable ANSI escape processing on Win10+ consoles
            import ctypes
            try:
                _kernel32 = ctypes.windll.kernel32
                _kernel32.SetConsoleMode(_kernel32.GetStdHandle(-11), 7)
            except Exception:
                pass
except Exception:
    _USE_COLOR = False

# Palette roughly matching the app's "Super Research" brand — blue accent
# (matches "Super" in the header), dim grey for auxiliary lines, soft green
# for ok marks, amber for warn. Numeric codes are ANSI 256-color.
_ACCENT   = "\033[38;5;75m"   # bright blue — matches app brand
_DIM      = "\033[38;5;244m"  # muted grey
_OK       = "\033[38;5;108m"  # muted green
_WARN     = "\033[38;5;214m"  # amber
_BRIGHT   = "\033[38;5;231m"  # glowing white — for 'resurgam' rising-from-rest vibe
_RED      = "\033[38;5;160m"  # dignified deep red — for 'requiescat' resting vibe
_BOLD     = "\033[1m"
_RESET    = "\033[0m"

def _c(color: str, text: str) -> str:
    return f"{color}{text}{_RESET}" if _USE_COLOR else text

# Signature glyph — appears before every command's Latin tagline. Subtle
# enough not to read as decoration, specific enough to make any `serve` /
# `pair` / `resurrect` / `retire` / `unpair` terminal output instantly
# recognizable as Super Research.
_SIGIL = "◆"

# Braille-dot spinner — used during `--pair`'s wait-for-app-to-claim-token
# loop and anywhere else we poll a slow Firestore condition. Ten frames
# cycled at ~100ms gives a calm, continuous rotation that reads as "alive,
# still working" without feeling impatient.
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _branded_header(tagline_text: str, tagline_color: str, tagline_gloss: str):
    """Shared banner for every subcommand (--pair / --serve / --resurrect /
    --retire / --unpair). Renders the SUPER RESEARCH wordmark, then a single
    line carrying the signature ◆ glyph, the Latin tagline in the caller's
    chosen color, and a dim English gloss — so every command reads as part
    of one matched set while the motto still signals the action's vibe.

    tagline_color is a foreground escape; BOLD is added by the caller inside
    the _c(...) call so different commands can pick different weights."""
    bar = _c(_DIM, "━" * 62)
    print()
    print(f"  {bar}")
    print()
    print(f"                   {_c(_BOLD + _ACCENT, 'SUPER')} {_c(_BOLD, 'RESEARCH')}")
    print(
        f"                {_c(tagline_color, _SIGIL)}  "
        f"{_c(tagline_color, tagline_text)} {_c(_DIM, '·')} "
        f"{_c(_DIM, tagline_gloss)}"
    )
    print()
    print(f"  {bar}")


def _setup_logo():
    """Branded header for --pair. Thin wrapper around _branded_header so
    --pair wears the same crown as the other four commands, plus a compact
    4-step preview line so the user sees the whole arc before step [1/4]
    starts."""
    _branded_header("vinculum", _BOLD + _ACCENT, "the bond is forged")
    print()
    print(
        f"  {_c(_DIM, 'Four steps:')}   "
        f"{_c(_ACCENT, '1')} Token   {_c(_DIM, '→')}   "
        f"{_c(_ACCENT, '2')} On StartUp   {_c(_DIM, '→')}   "
        f"{_c(_ACCENT, '3')} Logins   {_c(_DIM, '→')}   "
        f"{_c(_ACCENT, '4')} Serve"
    )


def _setup_step(n: int, total: int, title: str):
    """Section header for each step inside a subcommand (pair / resurrect /
    retire / unpair). Dim underline gives a consistent visual rhythm between
    phases without requiring each caller to track its own state."""
    print()
    print(f"  {_c(_ACCENT + _BOLD, f'[{n}/{total}]')} {_c(_BOLD, title)}")
    print(f"  {_c(_DIM, '─' * 58)}")


def _render_context_strip(items: list[tuple[str, str]]):
    """Print a 'metadata strip' of (label, preformatted_value) pairs right
    after _branded_header, before any [n/total] step counters fire. Gives
    every subcommand the same 'here's where you are' header that --serve's
    Paired to / Token / Local API / Heartbeat block already nails.

    Caller pre-formats values (so green `(active)` chips, dim fallbacks,
    etc. are its call). Labels auto-pad to the longest one so the right
    column aligns without manual column math in every caller."""
    if not items:
        return
    label_width = max(len(lab) for lab, _ in items)
    print()
    for lab, val in items:
        print(f"  {_c(_DIM, (lab + ':').ljust(label_width + 2))}  {val}")


def _fetch_paired_email(paired_uid: str | None) -> str:
    """Best-effort lookup of the user's email for display. Returns empty
    string if Firestore is unreachable or the uid is unknown — callers
    fall back to showing '(not paired)' or the truncated uid."""
    if not paired_uid or not _firebase_db:
        return ""
    try:
        snap = _firebase_db.collection("users").document(paired_uid).get()
        if snap.exists:
            return (snap.to_dict() or {}).get("email", "") or ""
    except Exception:
        pass
    return ""


def _render_next_actions(items: list[tuple[str, str]]):
    """Print a compact 'Next' block at the tail of every subcommand: 2-3
    likely follow-up commands with one-liner purposes. items = [(command,
    description), ...]. Gives the user a consistent discovery surface for
    adjacent tooling so they're not hunting through --help or memory."""
    if not items:
        return
    bar = _c(_DIM, "┈" * 62)
    cmd_width = min(max(len(c) for c, _ in items), 40)
    print()
    print(f"  {bar}")
    print(f"  {_c(_DIM, 'Next')}")
    for cmd, desc in items:
        print(f"    {_c(_ACCENT, '→')}  {_c(_BOLD, cmd.ljust(cmd_width))}   {_c(_DIM, desc)}")
    print()


class _SyncSpinnerCtx:
    """Context manager rendering a Braille-dot spinner on a single line
    until the block exits. Used around short sync poll loops (--retire kill
    wait, --resurrect daemon-loop appearance, --unpair process cleanup)
    so 5-8s of otherwise silent wall-clock time reads as 'alive' to the
    user. Single \\r-overwritten line — no scroll noise."""
    def __init__(self, label: str):
        self.label = label
        import threading as _threading
        self._threading = _threading
        self._stop = _threading.Event()
        self._thread: _threading.Thread | None = None

    def _spin(self):
        i = 0
        start = time.time()
        while not self._stop.is_set():
            frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]
            elapsed = int(time.time() - start)
            sys.stdout.write(
                f"\r  {_c(_ACCENT, frame)}  {_c(_DIM, self.label + '…')}   "
                f"{_c(_DIM, f'{elapsed}s')}    "
            )
            sys.stdout.flush()
            i += 1
            time.sleep(0.1)

    def __enter__(self):
        self._thread = self._threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        sys.stdout.write("\r" + " " * 78 + "\r")
        sys.stdout.flush()
        return False


def _sync_spinner_ctx(label: str) -> _SyncSpinnerCtx:
    return _SyncSpinnerCtx(label)


class _AsyncSpinnerCtx:
    """Async variant of _sync_spinner_ctx — same visual, async-friendly
    so it composes with `async with` inside run_pair without blocking the
    event loop. Used in --pair step 4 while the supervisor spawn is
    waited on (~5s)."""
    def __init__(self, label: str):
        self.label = label
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def _spin(self):
        i = 0
        start = time.time()
        while not self._stop.is_set():
            frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]
            elapsed = int(time.time() - start)
            sys.stdout.write(
                f"\r  {_c(_ACCENT, frame)}  {_c(_DIM, self.label + '…')}   "
                f"{_c(_DIM, f'{elapsed}s')}    "
            )
            sys.stdout.flush()
            i += 1
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=0.1)
            except asyncio.TimeoutError:
                pass

    async def __aenter__(self):
        self._task = asyncio.create_task(self._spin())
        return self

    async def __aexit__(self, *exc):
        self._stop.set()
        if self._task is not None:
            try:
                await self._task
            except Exception:
                pass
        sys.stdout.write("\r" + " " * 78 + "\r")
        sys.stdout.flush()
        return False


def _async_spinner_ctx(label: str) -> _AsyncSpinnerCtx:
    return _AsyncSpinnerCtx(label)


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
_research_token = None  # ResearchToken: this backend instance's unique ID

# Shared queue state: mutated by the job worker in run_server, read by the
# Firestore start listener (module-level function) so queued research docs
# know the current backend busy state + what they're waiting behind.
_QUEUE_STATE = {"running": False, "current_job": None, "queue_ref": None, "recompute_fn": None}


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
_heartbeat_task = None  # Async task: writes lastHeartbeat every 5s
# Heartbeat cadence. Paired with the frontend's 15s offline threshold at
# `DEVICE_OFFLINE_THRESHOLD_MS` in web/src/lib/firestore.ts so missing
# two consecutive ticks + a ~5s slack flips the UI to offline. Cadence
# tightened over two passes (30→15→5) because user kept observing the
# "device killed, tile still green" gap and asked for near-realtime.
# Cost: 12 writes/min/device on token + device docs — negligible at
# personal-usage scale.
HEARTBEAT_INTERVAL_SEC = 5

RESEARCH_CONFIG_PATH = Path(__file__).parent / "research_config.json"
# Legacy path — auto-migrated on first load so existing users don't lose their token.
_LEGACY_PIPE_CONFIG_PATH = Path(__file__).parent / "pipe_config.json"


def _atomic_write_json(path: Path, data: dict) -> None:
    """Atomic JSON dump: write to a sibling temp file, os.replace onto the
    target. Guarantees readers in another process/thread never see a
    partial or truncated file — os.replace is atomic on Windows + POSIX
    when source and destination are on the same volume (which they are,
    same directory). Prevents the "concurrent --pair + serve heartbeat +
    daemon-loop respawn" race where a reader would catch mid-write garbage,
    json.loads would throw, the reader's subsequent save_device_config
    would write back with a default-{} config, wiping deviceId, and the
    next write_device_doc call would mint a new deviceId → duplicate
    device doc in Firestore."""
    import tempfile
    parent = str(path.parent)
    fd, tmp_path = tempfile.mkstemp(dir=parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except Exception:
                pass
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise


def load_research_token():
    """Load ResearchToken from local research_config.json (or RESEARCH_TOKEN env var).
    Returns the token string or None if not set up yet.

    Auto-migrates old pipe_config.json → research_config.json if found (one-time).
    """
    global _research_token
    # Env var takes precedence (for Docker/CI deployments)
    env_token = os.environ.get("RESEARCH_TOKEN", "").strip() or os.environ.get("PIPE_TOKEN", "").strip()
    if env_token:
        _research_token = env_token
        return _research_token

    # One-time migration: pipe_config.json → research_config.json
    if _LEGACY_PIPE_CONFIG_PATH.exists() and not RESEARCH_CONFIG_PATH.exists():
        try:
            legacy = json.loads(_LEGACY_PIPE_CONFIG_PATH.read_text(encoding="utf-8"))
            migrated = {
                "researchToken": legacy.get("pipeToken", "").strip(),
                "machineName": legacy.get("machineName", ""),
            }
            if migrated["researchToken"]:
                _atomic_write_json(RESEARCH_CONFIG_PATH, migrated)
                log(f"Migrated pipe_config.json → research_config.json")
        except Exception as e:
            log(f"Migration of pipe_config.json failed: {e}", "WARN")

    if RESEARCH_CONFIG_PATH.exists():
        try:
            cfg = json.loads(RESEARCH_CONFIG_PATH.read_text(encoding="utf-8"))
            _research_token = (cfg.get("researchToken") or cfg.get("pipeToken") or "").strip() or None
            return _research_token
        except Exception:
            pass
    return None


def generate_research_token():
    """Mint a new ResearchToken and register it in Firestore. Does NOT
    persist it to research_config.json — the caller is expected to call
    _persist_research_token_locally() only AFTER the pairing link is
    confirmed, so a mid-pair Ctrl+C or timeout leaves no trace on disk.
    The Firestore side is torn down by run_pair's abort cleanup if the
    link never completes. Called during --pair; returns the token string.
    """
    import uuid
    import socket
    global _research_token
    token = str(uuid.uuid4())
    machine_name = socket.gethostname()

    if _firebase_db:
        try:
            from google.cloud.firestore import SERVER_TIMESTAMP
            _firebase_db.collection("research_tokens").document(token).set({
                "status": "active",
                "machineName": machine_name,
                "createdAt": SERVER_TIMESTAMP,
                "lastHeartbeat": SERVER_TIMESTAMP,
            })
            log(f"ResearchToken registered in Firestore: {token[:8]}...")
        except Exception as e:
            log(f"Failed to register ResearchToken in Firestore: {e}", "WARN")

    _research_token = token
    return token


def _persist_research_token_locally(token: str):
    """Merge researchToken + machineName into research_config.json. Called
    by --pair only after the app-side link is confirmed, so an aborted
    setup never leaves a token on disk that re-runs would blindly reuse.
    Safe to call on a reused token too (idempotent merge write)."""
    import socket
    machine_name = socket.gethostname()
    local_cfg = {}
    if RESEARCH_CONFIG_PATH.exists():
        try:
            local_cfg = json.loads(RESEARCH_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    local_cfg["researchToken"] = token
    local_cfg["machineName"] = machine_name
    _atomic_write_json(RESEARCH_CONFIG_PATH, local_cfg)
    log(f"ResearchToken saved to {RESEARCH_CONFIG_PATH.name}")


# ── Device registry (multi-device support) ─────────────────────────────────
# A "device" is a paired backend PC. One doc per device lives at
# users/{uid}/devices/{deviceId}. Multiple devices let a user run concurrent
# research on different machines. The deviceId is stable across --pair runs
# on the same machine (stored in research_config.json) so re-pairing preserves
# the user's rename + supervised toggle.

_device_id: str | None = None
_device_paired_uid: str | None = None


def load_device_id():
    """Return the deviceId persisted in research_config.json, or None."""
    global _device_id
    if _device_id:
        return _device_id
    if RESEARCH_CONFIG_PATH.exists():
        try:
            cfg = json.loads(RESEARCH_CONFIG_PATH.read_text(encoding="utf-8"))
            _device_id = (cfg.get("deviceId") or "").strip() or None
            return _device_id
        except Exception:
            pass
    return None


def load_paired_uid():
    """Return the Firebase uid this device is paired to (from config file),
    or None if --pair hasn't completed yet."""
    global _device_paired_uid
    if _device_paired_uid:
        return _device_paired_uid
    if RESEARCH_CONFIG_PATH.exists():
        try:
            cfg = json.loads(RESEARCH_CONFIG_PATH.read_text(encoding="utf-8"))
            _device_paired_uid = (cfg.get("pairedUid") or "").strip() or None
            return _device_paired_uid
        except Exception:
            pass
    return None


def save_device_config(device_id: str | None = None, paired_uid: str | None = None):
    """Merge-write device_id / paired_uid into research_config.json."""
    global _device_id, _device_paired_uid
    local_cfg = {}
    if RESEARCH_CONFIG_PATH.exists():
        try:
            local_cfg = json.loads(RESEARCH_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    if device_id:
        local_cfg["deviceId"] = device_id
        _device_id = device_id
    if paired_uid:
        local_cfg["pairedUid"] = paired_uid
        _device_paired_uid = paired_uid
    _atomic_write_json(RESEARCH_CONFIG_PATH, local_cfg)


def clear_paired_uid():
    """Wipe pairedUid from memory + research_config.json without touching
    deviceId or researchToken. Used when the relink watcher sees linkedUid
    cleared — local state must forget the old owner so the heartbeat stops
    recreating the device doc under their account. deviceId + researchToken
    stay put so a subsequent relink (via paste-token) resumes without a
    re-setup."""
    global _device_paired_uid
    _device_paired_uid = None
    if not RESEARCH_CONFIG_PATH.exists():
        return
    try:
        local_cfg = json.loads(RESEARCH_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    if "pairedUid" not in local_cfg:
        return
    local_cfg.pop("pairedUid", None)
    try:
        _atomic_write_json(RESEARCH_CONFIG_PATH, local_cfg)
    except Exception as e:
        log(f"Could not clear pairedUid from config: {e}", "WARN")


def generate_device_id():
    """Mint a new stable deviceId shaped '<sanitized-hostname>-<6-char-hex>'.
    Called once per machine — subsequent --pair runs reuse the persisted id."""
    import uuid
    import socket
    import re as _re
    hostname = socket.gethostname()
    sanitized = _re.sub(r'[^a-z0-9-]', '-', hostname.lower()).strip('-')
    if not sanitized:
        sanitized = "device"
    new_id = f"{sanitized[:30]}-{uuid.uuid4().hex[:6]}"
    save_device_config(device_id=new_id)
    return new_id


def _detect_supervised() -> bool:
    """Probe Windows Task Scheduler for the SuperResearchBackend task. The
    scheduled task is the actual source of truth for supervised mode —
    the device doc is just a Firestore mirror that can drift (e.g., after
    unlink deletes the doc but the task lives on). Returns False on
    non-Windows platforms or when schtasks isn't available."""
    import platform as _platform
    if _platform.system() != "Windows":
        return False
    import subprocess as _sp
    try:
        result = _sp.run(
            ["schtasks", "/Query", "/TN", _SUPERVISOR_TASK_NAME],
            capture_output=True,
            timeout=5,
            creationflags=0x08000000,  # CREATE_NO_WINDOW — avoid flashing console
        )
        return result.returncode == 0
    except Exception:
        return False


def write_device_doc(uid: str, token: str, device_name: str | None = None):
    """Upsert users/{uid}/devices/{deviceId}. Preserves user-editable `name`
    from any prior doc and auto-detects `supervised` from the real
    scheduled task (so unlink+relink doesn't lose the toggle). Call once
    from --pair after pairing succeeds, and again from --serve startup to
    refresh token + heartbeat if the token changed."""
    if not _firebase_db or not uid or not token:
        return
    import socket as _socket
    import platform as _platform
    device_id = load_device_id() or generate_device_id()
    hostname = _socket.gethostname()
    try:
        os_str = f"{_platform.system()} {_platform.release()}"
    except Exception:
        os_str = _platform.system() or ""
    doc_ref = _firebase_db.collection("users").document(uid) \
        .collection("devices").document(device_id)
    existing = {}
    try:
        snap = doc_ref.get()
        if snap.exists:
            existing = snap.to_dict() or {}
    except Exception:
        pass
    payload = {
        "id": device_id,
        "hostname": hostname,
        "os": os_str,
        "token": token,
        # Millis-as-int (NOT SERVER_TIMESTAMP). Frontend reads it as a number
        # and compares `Date.now() - lastHeartbeat`; a Firestore Timestamp
        # object would coerce to NaN and the device would look permanently
        # offline even while the backend is heartbeating normally.
        "lastHeartbeat": int(time.time() * 1000),
        # Auto-detect supervised from the scheduled task so the toggle
        # survives unlink+relink (task isn't uninstalled by unlink). If
        # schtasks says "installed", we overwrite whatever was in the doc;
        # the task is the truth.
        "supervised": _detect_supervised(),
    }
    # Name field rules:
    #  - If --pair passed an explicit device_name, honor it (user typed
    #    it at the device-name prompt — overrides any prior value).
    #  - Else on first write, default to hostname.
    #  - Else preserve the existing (user may have renamed via Account
    #    page or a previous setup; heartbeat/relink writers must not
    #    clobber it).
    if device_name:
        payload["name"] = device_name
    elif "name" not in existing:
        payload["name"] = hostname
    if "registeredAt" not in existing:
        payload["registeredAt"] = int(time.time() * 1000)
    try:
        doc_ref.set(payload, merge=True)
        log(f"Device doc updated: users/{uid}/devices/{device_id}")
    except Exception as e:
        log(f"Failed to write device doc: {e}", "WARN")


async def _heartbeat_loop():
    """Write lastHeartbeat to research_tokens/{token} AND the paired device
    doc every 30s so the frontend can show Online/Offline status per device.

    Token doc uses SERVER_TIMESTAMP (frontend reads `.seconds` off the
    Timestamp). Device doc uses millis-as-int — the frontend compares
    `Date.now() - lastHeartbeat` directly, so a Timestamp object would
    become NaN and the tile would look perpetually offline. """
    from google.cloud.firestore import SERVER_TIMESTAMP
    while True:
        try:
            if _firebase_db and _research_token:
                _firebase_db.collection("research_tokens").document(_research_token).update({
                    "lastHeartbeat": SERVER_TIMESTAMP,
                    "status": "active",
                })
                # Mirror to device doc for the per-device status indicator.
                # Skip silently when no paired uid is pinned — either setup
                # hasn't run yet, or the user just unlinked and the relink
                # watcher cleared pairedUid. The token heartbeat above keeps
                # firing so the relink watcher (which sits on the token doc)
                # stays responsive; we just stop writing under the old
                # owner's account. A relink restores pairedUid and the next
                # tick recreates the device doc under the new owner.
                paired_uid = load_paired_uid()
                device_id = load_device_id()
                if paired_uid and device_id:
                    try:
                        _firebase_db.collection("users").document(paired_uid) \
                            .collection("devices").document(device_id).update({
                                "lastHeartbeat": int(time.time() * 1000),
                            })
                    except Exception:
                        # Doc missing but pairedUid still set — either a
                        # transient Firestore blip or the relink watcher
                        # hasn't yet seen the unlink event. Leave it alone;
                        # if the unlink is real, the relink watcher will
                        # call clear_paired_uid() shortly and subsequent
                        # ticks skip the mirror block entirely.
                        pass
        except Exception as e:
            log(f"Heartbeat write failed: {e}", "WARN")
        await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)


_token_relink_watch = None  # Firestore Watch handle; kept for lifetime cleanup


def _start_token_relink_watcher(token: str):
    """Subscribe to research_tokens/{token} and react to linkedUid flips in
    real time, so a user pasting the token into the Account page gets their
    device tile back in well under a second instead of waiting up to ~30s
    for the next heartbeat. The heartbeat self-heal at _heartbeat_loop() is
    kept as a safety net in case the watcher drops.

    The Firestore Admin SDK fires the snapshot callback in a background
    thread — we do sync work only (write_device_doc + save_device_config).
    Idempotent against repeated snapshots for the same uid. """
    global _token_relink_watch
    if not _firebase_db or not token:
        return
    doc_ref = _firebase_db.collection("research_tokens").document(token)

    def _on_snap(snapshots, changes, read_time):
        try:
            for snap in snapshots:
                data = snap.to_dict() or {}
                new_uid = (data.get("linkedUid") or "").strip()
                current_uid = load_paired_uid() or ""
                # Unlink event: linkedUid was cleared. Forget the old owner
                # locally so the heartbeat stops mirroring to their device
                # path (otherwise the Account tile reappears within 30s).
                # Token + deviceId stay intact — a relink from any user with
                # the same token restores pairing without re-setup.
                if not new_uid:
                    if current_uid:
                        log(f"Token unlinked (linkedUid cleared for paired uid {current_uid[:8]}…) — clearing local pairedUid; heartbeat will stop mirroring until relink.")
                        clear_paired_uid()
                    continue
                if new_uid == current_uid:
                    continue
                log(f"Token relinked → {new_uid[:8]}… — refreshing device doc now.")
                try:
                    save_device_config(paired_uid=new_uid)
                    write_device_doc(new_uid, token)
                except Exception as e:
                    log(f"Relink refresh failed: {e}", "WARN")
        except Exception as e:
            log(f"Relink watcher callback error: {e}", "WARN")

    try:
        _token_relink_watch = doc_ref.on_snapshot(_on_snap)
        log("Token relink watcher started")
    except Exception as e:
        log(f"Could not start relink watcher (falling back to 30s heartbeat): {e}", "WARN")


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


def save_document_to_firestore(doc_type: str, content: str, name: str | None = None) -> bool:
    """Upsert a research document (brief/chatgpt/gemini/claude/consolidated)
    into the user's Firestore documents subcollection so the Documents page
    on Vercel can render it without direct access to this local backend.
    Phase 3 (NotebookLM) still reads MDs from queue_dir/documents/ on local
    disk — this sync is strictly for the frontend Documents UI.

    Upsert semantics: doc_type is used as the Firestore doc ID, so re-runs
    or re-extractions for the same research overwrite in place instead of
    creating duplicates.

    Returns True iff the Firestore write committed; False otherwise (no
    Firestore client, blank content, or API error). Callers gate the
    `link_extracted` emit on this so an unsynced doc never gets a "Read
    report" button that would open an empty modal.
    """
    if not _firebase_db or not _fb_uid or not _fb_research_id:
        return False
    if not content or not content.strip():
        return False
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
        return True
    except Exception as e:
        log(f"Failed to sync {doc_type}.md to Firestore: {e}", "WARN")
        return False


def start_firestore_start_listener(job_queue, loop):
    """Listen for pipeline start requests via this backend's ResearchToken queue.
    Frontend writes to: research_tokens/{token}/queue/{auto-id}
    Backend picks it up, queues the job, writes run_id back.
    Falls back to global pipeline_requests/ if no ResearchToken is set (legacy)."""
    global _start_listener
    if not _firebase_db:
        return

    # Token-scoped queue (preferred) vs legacy global collection
    if _research_token:
        col_ref = _firebase_db.collection("research_tokens").document(_research_token).collection("queue")
        listener_label = f"research_tokens/{_research_token[:8]}…/queue/"
    else:
        col_ref = _firebase_db.collection("pipeline_requests")
        listener_label = "pipeline_requests/ (legacy — run --pair to get a ResearchToken)"

    def on_snapshot(col_snapshot, changes, read_time):
        for change in changes:
            if change.type.name != 'ADDED':
                continue
            doc = change.document
            data = doc.to_dict() or {}
            if data.get("processed"):
                continue
            # Stale-queue defense: Firestore's onSnapshot replays every
            # existing unprocessed doc as ADDED on first attach. If a
            # previous serve session wrote a start request but crashed /
            # exited before marking processed, that doc replays on the
            # NEXT serve startup and silently kicks off a research the
            # user never asked for. This has killed multiple test
            # sessions. Mirrors the stale-command defense in
            # _start_command_listener.
            # Threshold past the frontend's worst-case command round-trip
            # so legitimate "just-fired" starts always pass.
            STALE_QUEUE_AGE_MS = 30_000
            _ts = data.get("timestamp")
            if isinstance(_ts, (int, float)) and _ts > 0:
                _age_ms = int(time.time() * 1000) - int(_ts)
                if _age_ms > STALE_QUEUE_AGE_MS:
                    try:
                        doc.reference.update({"processed": True, "staleSkipped": True})
                    except Exception:
                        pass
                    log(f"Queue: skipped stale doc (age={_age_ms // 1000}s, action={data.get('action', 'start')})", "INFO")
                    continue
            action = data.get("action", "start")
            # Handle cancel-queued: remove the target research from the job
            # queue before it reaches the worker and mark it stopped. The
            # actively-running job is handled by its own per-run command
            # listener, not here.
            if action == "cancel":
                target_rid = data.get("researchId", "")
                target_uid = data.get("uid", "")
                if not target_rid or not target_uid:
                    try:
                        doc.reference.update({"processed": True, "error": "missing researchId/uid"})
                    except Exception:
                        pass
                    continue
                # Don't interfere with the actively-running job — per-run
                # command listener handles it via its own stop path.
                current = _QUEUE_STATE.get("current_job") or {}
                if current.get("research_id") == target_rid:
                    log(f"Cancel: target {target_rid} is actively running — skipping queue surgery", "INFO")
                    try:
                        doc.reference.update({"processed": True, "note": "actively running; use stop"})
                    except Exception:
                        pass
                    continue
                def _do_cancel(rid=target_rid, u=target_uid, dref=doc.reference):
                    try:
                        dq = job_queue._queue  # deque
                        kept = [j for j in dq if j.get("research_id") != rid]
                        removed = any(j.get("research_id") == rid for j in dq)
                        dq.clear()
                        for j in kept:
                            dq.append(j)
                        if removed and _firebase_db:
                            try:
                                _firebase_db.collection("users").document(u) \
                                    .collection("researches").document(rid) \
                                    .update({
                                        "status": "stopped",
                                        "phase": 0,
                                        "summary": "Cancelled before starting",
                                    })
                            except Exception as ex:
                                log(f"Cancel: failed to mark stopped: {ex}", "WARN")
                            fn = _QUEUE_STATE.get("recompute_fn")
                            if fn:
                                fn()
                        try:
                            dref.update({"processed": True, "cancelled": removed})
                        except Exception:
                            pass
                    except Exception as ex:
                        log(f"Cancel queued failed: {ex}", "WARN")
                loop.call_soon_threadsafe(_do_cancel)
                continue
            if action != "start":
                continue
            uid = data.get("uid", "")
            research_id = data.get("researchId", "")
            topic = data.get("topic", "").strip()
            email = data.get("email", "")
            config = data.get("config", {})
            brief_text = (data.get("briefText") or "").strip()
            if not topic or not uid or not research_id:
                log(f"Firestore start request missing fields: uid={uid}, rid={research_id}, topic={topic[:30]}", "WARN")
                try:
                    doc.reference.update({"processed": True, "error": "missing fields"})
                except Exception:
                    pass
                continue
            # Token-unlink guard: a device that was unpaired from Account
            # settings clears linkedUid on the token doc. The queue listener
            # itself stays alive (we may relink later), but we must reject
            # any start requests that arrive between unlink and relink —
            # otherwise the backend happily processes work for a device the
            # user revoked. Also enforces uid match so a stolen token can't
            # trigger runs against someone else's account.
            if _research_token:
                try:
                    tdoc = _firebase_db.collection("research_tokens").document(_research_token).get()
                    tdata = tdoc.to_dict() or {}
                    linked_uid = (tdata.get("linkedUid") or "").strip()
                    if not linked_uid:
                        log(f"Rejecting start: token unlinked (linkedUid empty). uid={uid[:8]} topic={topic[:40]}", "WARN")
                        try:
                            doc.reference.update({"processed": True, "error": "token unlinked"})
                        except Exception:
                            pass
                        continue
                    if uid != linked_uid:
                        log(f"Rejecting start: uid mismatch (linked={linked_uid[:8]} req={uid[:8]})", "WARN")
                        try:
                            doc.reference.update({"processed": True, "error": "uid mismatch"})
                        except Exception:
                            pass
                        continue
                except Exception as e:
                    log(f"Token validation failed (allowing request through): {e}", "WARN")
            # Research-doc existence check — user may have deleted the chat
            # from the app between firing the research and us picking up the
            # queue doc. Without this, we'd run a full pipeline and try to
            # write back status to a doc that doesn't exist (the "404 No
            # document to update" WARN the user saw), which wastes an hour
            # of API calls on work the user already abandoned. Mark the
            # queue doc staleSkipped so it doesn't replay on future
            # listener attaches.
            try:
                research_doc = _firebase_db.collection("users").document(uid) \
                    .collection("researches").document(research_id).get()
                if not research_doc.exists:
                    log(f"Queue: skipped — research doc {research_id} no longer exists (user deleted chat?)", "INFO")
                    try:
                        doc.reference.update({"processed": True, "staleSkipped": True,
                                              "reason": "research doc deleted"})
                    except Exception:
                        pass
                    continue
            except Exception as e:
                log(f"Queue: research-doc existence check failed (allowing through): {e}", "WARN")

            # Generate run_id
            run_id = f"{safe_name(topic)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            log(f"Firestore start: uid={uid[:8]}... topic={topic[:40]} run_id={run_id}")
            # Decide initial status: "ongoing" if worker is idle, else "queued"
            # with position + behind-target so the chat banner + tile badge can
            # tell the user which run must finish first.
            is_busy = bool(_QUEUE_STATE.get("running")) or job_queue.qsize() > 0
            if is_busy:
                # Position in queue = current pending + 1 (this one)
                position = job_queue.qsize() + 1
                behind_rid = ""
                behind_title = ""
                current = _QUEUE_STATE.get("current_job")
                if current:
                    behind_rid = current.get("research_id") or ""
                    behind_title = (current.get("topic") or "")[:60]
                elif job_queue.qsize() > 0:
                    try:
                        pending_list = list(job_queue._queue)  # snapshot deque
                        if pending_list:
                            first = pending_list[0]
                            behind_rid = first.get("research_id") or ""
                            behind_title = (first.get("topic") or "")[:60]
                    except Exception:
                        pass
                status_payload = {
                    "backendRunId": run_id,
                    "status": "queued",
                    "queuePosition": position,
                    "queuedBehindRunId": behind_rid,
                    "queuedBehindTitle": behind_title,
                }
            else:
                status_payload = {"backendRunId": run_id, "status": "ongoing"}
            # Write run_id + initial status back to the research doc
            try:
                _firebase_db.collection("users").document(uid) \
                    .collection("researches").document(research_id) \
                    .update(status_payload)
            except Exception as e:
                log(f"Failed to write backendRunId: {e}", "WARN")
                try:
                    _firebase_db.collection("users").document(uid) \
                        .collection("researches").document(research_id) \
                        .set(status_payload, merge=True)
                except Exception:
                    pass
            # Mark processed
            try:
                doc.reference.update({"processed": True, "run_id": run_id})
            except Exception:
                pass
            # Queue the job (default-arg capture avoids lambda-in-loop closure bug)
            loop.call_soon_threadsafe(
                lambda t=topic, e=email, c=config, r=run_id, u=uid, ri=research_id, bt=brief_text:
                    job_queue.put_nowait(
                        {"topic": t, "email": e, "config": c, "run_id": r,
                         "uid": u, "research_id": ri, "brief_text": bt}
                    )
            )

    _start_listener = col_ref.on_snapshot(on_snapshot)
    log(f"Firestore start listener active on {listener_label}")


def setup_firestore_run(uid, research_id, loop=None, run_id=None):
    """Set per-run Firestore context. Call at pipeline start."""
    global _fb_uid, _fb_research_id, _fb_seq, _fb_listener
    _fb_uid = uid
    _fb_research_id = research_id
    _fb_seq = 0
    # Persist owner so the DELETE endpoint can cascade-delete Firestore
    # subcollections when the user purges a run from disk. Without this, the
    # DELETE endpoint only knows the backend run_id and would leave partial
    # docs/audios orphaned in Firestore.
    if run_id and uid and research_id:
        try:
            queue_dir = Path(__file__).parent / "queues" / run_id
            queue_dir.mkdir(parents=True, exist_ok=True)
            (queue_dir / "owner.json").write_text(
                json.dumps({"uid": uid, "researchId": research_id}),
                encoding="utf-8",
            )
        except Exception as _e:
            log(f"owner.json write failed: {_e}", "WARN")
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


_exit_scheduled = False


def _schedule_server_exit(source: str, delay_sec: float = 3.0):
    """Schedule a one-shot daemon thread that calls os._exit(0) after a short
    delay, giving the pipeline time to emit pipeline_stopped + close the
    browser cleanly. Idempotent: if the same run is stopped via BOTH the
    Firestore command listener AND the HTTP endpoint, we only spawn one
    exit thread. Called from whichever stop transport fires first.
    """
    global _exit_scheduled
    if _exit_scheduled:
        log(f"[{source}] Exit already scheduled — ignoring duplicate", "INFO")
        return
    _exit_scheduled = True
    import threading as _threading
    def _runner():
        import time as _t, os as _os
        _t.sleep(delay_sec)
        log(f"Exiting server after Stop ({source})", "WARN")
        _os._exit(0)
    _threading.Thread(target=_runner, daemon=True).start()


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


def _read_firestore_research_title(fallback=""):
    """Read the current `title` field from the research doc in Firestore.
    Frontend's /api/title fills this with a smart 4–8 word title right after
    pipeline start. Returns the fallback (typically topic[:60]) if empty."""
    if not _firebase_db or not _fb_uid or not _fb_research_id:
        return fallback
    try:
        snap = _firebase_db.collection("users").document(_fb_uid) \
            .collection("researches").document(_fb_research_id).get()
        if snap.exists:
            data = snap.to_dict() or {}
            title = (data.get("title") or "").strip()
            if title:
                return title
    except Exception as e:
        log(f"Firestore title read failed: {e}", "WARN")
    return fallback


def smart_title(topic: str) -> str:
    """Return the best short title for this run. Prefers the frontend-generated
    smart title in Firestore; falls back to topic[:60] cleaned up."""
    clean_fallback = (topic or "").strip().split("\n", 1)[0][:60].strip()
    return _read_firestore_research_title(fallback=clean_fallback) or clean_fallback


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
            # Stale-command defense: Firestore's onSnapshot replays every
            # existing doc as ADDED on first attach. If a previous session
            # wrote a stop/pause/etc and either (a) never reached the
            # mark-processed line (os._exit crashed the Firestore write) or
            # (b) the SDK buffered the write and the process died before
            # flush, that doc stays unprocessed forever. Next serve then
            # re-executes it the moment the listener reattaches — which has
            # killed multiple test sessions within seconds of startup.
            # 30s is well past the frontend's typical command round-trip,
            # so any command older than that is from a previous session.
            STALE_COMMAND_AGE_MS = 30_000
            _ts = data.get("timestamp")
            if isinstance(_ts, (int, float)) and _ts > 0:
                _age_ms = int(time.time() * 1000) - int(_ts)
                if _age_ms > STALE_COMMAND_AGE_MS:
                    # Mark it processed so it stops replaying on future
                    # listener attaches, but do NOT execute.
                    try:
                        doc.reference.update({"processed": True, "staleSkipped": True})
                    except Exception:
                        pass
                    continue
            action = data.get("action", "")
            if action == "ping":
                # Watchdog confirmation ping. Frontend writes this when it
                # suspects silence; our processing of the command proves
                # the backend is alive. Fast path — no _controls side
                # effects, just mark the doc processed with a pongedAt
                # timestamp the watchdog can read back.
                try:
                    doc.reference.update({
                        "processed": True,
                        "pongedAt": int(time.time() * 1000),
                    })
                except Exception:
                    pass
                continue
            if action == "stop":
                # Mark processed BEFORE scheduling the 3s exit timer so the
                # flag lands even if the Firestore Admin SDK buffers the
                # tail-end mark-processed write (at line ~1455) and
                # os._exit(0) kills the buffer before flush. Without this,
                # an ungraceful exit leaves the stop doc unprocessed and
                # the next serve replays it the moment the listener
                # reattaches — killing the fresh session within seconds.
                try:
                    doc.reference.update({"processed": True})
                except Exception:
                    pass
                loop.call_soon_threadsafe(_controls.request_stop)
                # Bridge: also create file sentinel for old phase-boundary checks
                if _tracks_dir:
                    try: (Path(__file__).parent / "queues" / _tracks_dir.name / ".stop").touch()
                    except Exception: pass
                log("Command received: STOP — server will exit after cleanup")
                _schedule_server_exit("firestore-command")
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
                # Only Phase 1 (brief generation) accepts add_context. Phase 2
                # agents are deep-research tools (ChatGPT Pro, Gemini Deep
                # Research, Claude with tools) that can't ingest mid-stream
                # input — and Phase 3+ artifacts (NotebookLM / YouTube / Doc)
                # don't take input either. Frontend locks the chat input from
                # Phase 2 onward; this listener is the belt-and-suspenders.
                if _runtime.phase >= 2:
                    log(f"Command received: ADD_CONTEXT IGNORED (phase={_runtime.phase} — input disabled from Phase 2 onward)", "WARN")
                elif text:
                    loop.call_soon_threadsafe(_controls.add_context, text)
                    log(f"Command received: ADD_CONTEXT ({len(text)} chars)")
            elif action == "config":
                cfg = data.get("config", {})
                if cfg:
                    loop.call_soon_threadsafe(_controls.update_config, cfg)
                    _write_config_to_disk(cfg)
                    log(f"Command received: CONFIG update (written to disk)")
            elif action == "skip_init_verify":
                # User bailed on Phase 0 login verification from the dropdown.
                loop.call_soon_threadsafe(_controls.request_skip_init_verify)
                log("Command received: SKIP_INIT_VERIFY — Phase 0 will proceed without full verify")
            elif action == "retry_init_verify":
                # User tapped Retry on the login_required banner. Same as
                # resume, but the frontend has already torn down the old
                # Phase 0 tile — backend will re-emit phase_start so a fresh
                # tile renders below the retry banner.
                loop.call_soon_threadsafe(_controls.request_retry_init_verify)
                log("Command received: RETRY_INIT_VERIFY — re-running Phase 0 with a fresh tile")
            elif action == "skip_agent":
                # Skip a stuck Phase 2 agent without stopping the rest of the
                # phase. The polling loop consumes _controls.skipped_agents on
                # its next tick: extracts partial output from that agent's
                # page and drops it from `pending`.
                _ag = (data.get("agent", "") or "").strip().lower()
                if _ag in ("chatgpt", "gemini", "claude"):
                    loop.call_soon_threadsafe(_controls.request_skip_agent, _ag)
                    log(f"Command received: SKIP_AGENT agent={_ag}")
                else:
                    log(f"Command received: SKIP_AGENT rejected — unknown agent '{_ag}'", "WARN")
            elif action == "skip_phase":
                # Abandon the current phase with whatever partial results we
                # have and jump to the next. Triggered by the watchdog banner
                # when the backend has been unresponsive for 45+ min and the
                # user picks "Skip phase".
                _ph = data.get("phase")
                try:
                    _ph = int(_ph) if _ph is not None else None
                except (TypeError, ValueError):
                    _ph = None
                if _ph is not None:
                    loop.call_soon_threadsafe(_controls.request_skip_phase, _ph)
                    # Also release any pause so the phase coroutine can exit cleanly
                    loop.call_soon_threadsafe(_controls.request_resume)
                    log(f"Command received: SKIP_PHASE phase={_ph}")
                else:
                    log("Command received: SKIP_PHASE rejected — no phase number", "WARN")
            elif action == "continue_anyway":
                # User dismissed a pipeline_warning (e.g. brief-short) and
                # told us to proceed without retry. Flag is one-shot — the
                # caller that emitted the warning consumes it on next check.
                loop.call_soon_threadsafe(_controls.set_continue_anyway)
                log("Command received: CONTINUE_ANYWAY — resuming past warning")
            elif action == "retry_phase":
                # User clicked "Retry Phase N" on a pipeline_warning. The
                # phase coroutine that emitted the warning is polling
                # consume_retry_phase(N) and will restart its body when it
                # sees the flag. Also releases any pause so the wait exits.
                _ph = data.get("phase")
                try:
                    _ph = int(_ph) if _ph is not None else None
                except (TypeError, ValueError):
                    _ph = None
                if _ph is not None:
                    loop.call_soon_threadsafe(_controls.request_retry_phase, _ph)
                    loop.call_soon_threadsafe(_controls.request_resume)
                    log(f"Command received: RETRY_PHASE phase={_ph}")
                else:
                    log("Command received: RETRY_PHASE rejected — no phase number", "WARN")
            elif action == "retry_agent":
                # User clicked "Retry [Agent]" on a Phase 2 agent warning.
                # Mode selector:
                #   "soft" (default) — polling pastes a follow-up into the
                #                      existing tab, preserves partial output
                #   "hard"           — polling closes the tab and re-runs the
                #                      full setup (fresh session, no partial)
                # Hard retry is capped at 2/agent/phase by the polling loop.
                #
                # 2026-04-25: when the agent failed BEFORE entering the
                # round-robin (setup/paste failure → not in `pending`), soft
                # retry is a no-op because there's no in-flight session to
                # paste into. Auto-promote to hard so the agent gets a fresh
                # tab + fresh setup attempt. The hard-retry consumer at
                # ~line 7271 also seeds `pending` for missing agents.
                _ag = (data.get("agent") or "").strip()
                _mode = (data.get("mode") or "soft").strip().lower()
                _ag_norm = _ag.lower()
                _agent_pre_failed = _ag_norm in (_controls.skipped_agents or set())
                if _ag and (_mode == "hard" or _agent_pre_failed):
                    loop.call_soon_threadsafe(_controls.request_retry_agent_hard, _ag)
                    if _agent_pre_failed:
                        # Drop the pre-fail skip marker so the hard-retry path
                        # doesn't see Gemini as still-skipped.
                        try:
                            _controls.skipped_agents.discard(_ag_norm)
                        except Exception:
                            pass
                        log(f"Command received: RETRY_AGENT agent={_ag} mode=hard (auto-promoted — agent had pre-pending setup failure)")
                    else:
                        log(f"Command received: RETRY_AGENT agent={_ag} mode=hard")
                elif _ag:
                    loop.call_soon_threadsafe(_controls.request_retry_agent, _ag)
                    log(f"Command received: RETRY_AGENT agent={_ag} mode=soft")
                else:
                    log("Command received: RETRY_AGENT rejected — no agent", "WARN")
            elif action == "continue_partial_agent":
                # User accepted an agent's short/timed-out output. Phase 2
                # polling finalizes the agent with status done_partial.
                _ag = (data.get("agent") or "").strip()
                if _ag:
                    loop.call_soon_threadsafe(_controls.request_continue_partial, _ag)
                    log(f"Command received: CONTINUE_PARTIAL_AGENT agent={_ag}")
                else:
                    log("Command received: CONTINUE_PARTIAL_AGENT rejected — no agent", "WARN")
            elif action == "poke_agent":
                # User clicked "Poke" on a stuck-agent warning. Phase 2 polling
                # sends a gentle "please continue" follow-up to the agent.
                _ag = (data.get("agent") or "").strip()
                if _ag:
                    loop.call_soon_threadsafe(_controls.request_poke_agent, _ag)
                    log(f"Command received: POKE_AGENT agent={_ag}")
                else:
                    log("Command received: POKE_AGENT rejected — no agent", "WARN")
            elif action == "wait_longer_agent":
                # User chose to wait another 10 min on a stuck agent. Phase 2
                # polling resets the no-growth timer.
                _ag = (data.get("agent") or "").strip()
                if _ag:
                    loop.call_soon_threadsafe(_controls.request_wait_longer_agent, _ag)
                    log(f"Command received: WAIT_LONGER_AGENT agent={_ag}")
                else:
                    log("Command received: WAIT_LONGER_AGENT rejected — no agent", "WARN")
            elif action == "agent_decision":
                # Frontend response to agent_link_failed modal.
                decision = (data.get("decision", "") or "").lower()
                agent = data.get("agent", "")
                if decision not in ("retry", "skip", "stop"):
                    log(f"Command received: AGENT_DECISION agent={agent} INVALID decision={decision}", "WARN")
                else:
                    loop.call_soon_threadsafe(_controls.set_agent_decision, decision)
                    if decision == "stop":
                        # Full stop semantics — match the dedicated STOP action:
                        # mark doc processed BEFORE scheduling exit (same
                        # reasoning as the top-level stop handler above),
                        # flip the asyncio event, write the sentinel, and
                        # schedule the server exit. Previously this path set
                        # only the event, leaving the backend alive.
                        try:
                            doc.reference.update({"processed": True})
                        except Exception:
                            pass
                        loop.call_soon_threadsafe(_controls.request_stop)
                        if _tracks_dir:
                            try: (Path(__file__).parent / "queues" / _tracks_dir.name / ".stop").touch()
                            except Exception: pass
                        _schedule_server_exit("agent-decision-stop")
                    # Release the pause so the phase coroutine can consume the decision
                    loop.call_soon_threadsafe(_controls.request_resume)
                    log(f"Command received: AGENT_DECISION agent={agent} decision={decision}")
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
        # B1: per-agent link-fail decision ("retry" | "skip" | "stop")
        self.pending_agent_decision: str | None = None
        # Phase 0: user-triggered mid-loop skip of the CUA verification gate.
        self.skip_init_verify: bool = False
        # Phase 0: user hit Retry on the login_required banner — triggers a
        # fresh phase_start emit so the frontend can render a new tile below.
        self.retry_init_verify: bool = False
        # Phase 2: per-agent skip requests. Sent by the watchdog's
        # BackendSilentBanner (when a specific agent is picked mid-stall) and
        # by HumanVerifyBanner's "Skip agent" button. Lower-case agent keys
        # (chatgpt, gemini, claude). The Phase 2 polling loop consumes these
        # on its next tick — drops the agent from `pending`, extracts whatever
        # partial output exists, and emits agent_skipped.
        self.skipped_agents: set[str] = set()
        # Watchdog banner's "Skip phase" button queues phase numbers here.
        # Each phase's coroutine checks is_phase_skip_requested(N) at its
        # natural yield points and exits early with phase_skipped when set.
        self.skipped_phases: set[int] = set()
        # Continue-anyway: user dismissed a pipeline_warning (e.g. "brief is
        # short") and asked the pipeline to keep going regardless. Callers
        # that emit the warning check+clear this flag to decide whether to
        # halt or proceed. One-shot — consumed on read.
        self.continue_anyway: bool = False
        # Retry-phase: user clicked "Retry Phase N" on a pipeline_warning
        # (e.g. brief-short, stuck agent). Set holds phase numbers that
        # the phase coroutine should restart. Each phase's short-output
        # branch calls await_retry_or_continue(N) to wait for the choice.
        self.retry_phase_requested: set[int] = set()
        # Retry-agent: user clicked "Retry [Agent]" on a Phase 2 agent
        # warning (timeout or empty-final). Phase 2 polling checks
        # consume_retry_agent(key) and submits a follow-up prompt.
        self.retry_agents: set[str] = set()
        # Hard retry-agent: user chose "Retry (hard)" on a Phase 2 agent
        # warning, or a handler escalated to hard semantics. Instead of
        # pasting a follow-up into the same tab, the polling loop closes
        # the page, re-runs start_agent_no_gemini_wait from scratch, and
        # replaces pending[name]. Use for session-expiry / broken-tab
        # cases where soft retry cannot recover. Capped at 2 per-agent
        # per-phase via pending[name]["hard_retry_count"] — above that,
        # falls through to soft retry.
        self.retry_agents_hard: set[str] = set()
        # Continue-partial: user accepted a Phase 2 agent's short/timed-out
        # output. Phase 2 polling finalizes the agent with status
        # "done_partial" / "timeout_partial".
        self.continue_partial_agents: set[str] = set()
        # Poke-agent: user clicked "Poke [Agent]" on a stuck-agent warning.
        # Phase 2 polling sends a mild "please continue" follow-up without
        # resetting the budget (unlike retry, which is a heavier restart).
        self.poke_agents: set[str] = set()
        # Wait-longer: user clicked "Wait longer" on a stuck-agent warning.
        # Resets the no-growth timer so the stuck detector grants another
        # 10-min window before re-prompting.
        self.wait_longer_agents: set[str] = set()

    def request_stop(self):
        self.stop_event.set()

    def request_pause(self):
        self.pause_event.set()

    def request_resume(self):
        self.pause_event.clear()
        self.resume_event.set()

    def set_agent_decision(self, decision: str):
        """Called from command listener when user chooses retry/skip/stop
        for an agent_link_failed prompt. Also releases the pause."""
        if decision in ("retry", "skip", "stop"):
            self.pending_agent_decision = decision

    def pop_agent_decision(self) -> str | None:
        d = self.pending_agent_decision
        self.pending_agent_decision = None
        return d

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
        self.pending_agent_decision = None
        self.skip_init_verify = False
        self.retry_init_verify = False
        self.skipped_agents.clear()
        self.skipped_phases.clear()
        self.continue_anyway = False
        self.retry_phase_requested.clear()
        self.retry_agents.clear()
        self.retry_agents_hard.clear()
        self.continue_partial_agents.clear()
        self.poke_agents.clear()
        self.wait_longer_agents.clear()

    def request_skip_init_verify(self):
        """User clicked 'Skip verification' in Phase 0 dropdown — bail the
        CUA loop and proceed to Phase 1. Also releases any pause so the
        login_required wait exits immediately."""
        self.skip_init_verify = True
        self.pause_event.clear()
        self.resume_event.set()

    def request_retry_init_verify(self):
        """User tapped Retry on the login_required banner. Distinct from a
        plain resume: sets a flag so Phase 0 re-emits phase_start before
        running the next verification attempt (frontend uses this to render
        a fresh Phase 0 tile below the retry banner, in chronological order)."""
        self.retry_init_verify = True
        self.pause_event.clear()
        self.resume_event.set()

    def request_skip_agent(self, agent: str):
        """User hit the Skip button on a stuck Phase 2 agent. The polling
        loop checks this set on every tick and drops any listed agent from
        `pending`, keeping the rest of the phase running."""
        key = (agent or "").strip().lower()
        if key:
            self.skipped_agents.add(key)

    def request_skip_phase(self, phase: int):
        """User picked "Skip phase" from the 45-min backend-silent banner.
        Each phase calls consume_phase_skip(N) at its entry branch — if True,
        the phase emits phase_skipped(reason=user_skip) instead of running,
        and the pipeline advances to the next phase with whatever partial
        results already exist."""
        try:
            self.skipped_phases.add(int(phase))
        except (TypeError, ValueError):
            pass

    def set_continue_anyway(self):
        """User clicked 'Continue anyway' on a pipeline_warning. One-shot —
        consumed by the next consume_continue_anyway() call. Also releases
        any pause so the caller coroutine can check the flag."""
        self.continue_anyway = True
        self.pause_event.clear()
        self.resume_event.set()

    def consume_continue_anyway(self) -> bool:
        """Check + clear the continue-anyway flag. Callers that emitted a
        pipeline_warning with a [continue_anyway] action call this to decide
        whether to proceed or retry/halt."""
        v = self.continue_anyway
        self.continue_anyway = False
        return v


    def request_retry_phase(self, phase: int):
        """User clicked 'Retry Phase N' on a pipeline_warning. Phase coroutine
        checks consume_retry_phase(N) after emitting the warning and re-runs
        the phase body if set. Also releases any pause so the waiting phase
        can consume the decision."""
        try:
            self.retry_phase_requested.add(int(phase))
        except (TypeError, ValueError):
            return
        self.pause_event.clear()
        self.resume_event.set()

    def consume_retry_phase(self, phase: int) -> bool:
        """Check + clear the retry flag for this phase."""
        try:
            p = int(phase)
        except (TypeError, ValueError):
            return False
        if p in self.retry_phase_requested:
            self.retry_phase_requested.discard(p)
            return True
        return False

    async def await_retry_or_continue(self, phase: int, timeout: float = 600.0) -> str:
        """Wait for the user to respond to a pipeline_warning offering
        [Retry Phase N] / [Continue anyway]. Returns one of:
            'retry'            — user clicked Retry
            'continue_anyway'  — user clicked Continue anyway
            'stop'             — pipeline stopped while waiting
            'timeout'          — neither flag set within timeout (caller defaults to continue)
        Polls every 0.5s."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self.stop_event.is_set():
                return "stop"
            if self.consume_retry_phase(phase):
                return "retry"
            if self.consume_continue_anyway():
                return "continue_anyway"
            await asyncio.sleep(0.5)
        return "timeout"

    async def await_phase_decision(self, phase: int, timeout: float = 86400.0) -> str:
        """Wait for the user to resolve a phase-level pipeline_error. Returns:
            'retry' — Retry clicked (consume_retry_phase)
            'skip'  — Skip clicked (consume_phase_skip)
            'stop'  — Stop clicked (stop_event)
            'timeout' — wait expired (24h default — effectively never)

        Used by all phase callers after fail_phase(...) to honor the
        never-die contract (ARCHITECTURE CHANGE 2026-04-18). Polls every
        0.5s; pause_event is also checked so an indefinite HV pause
        doesn't starve the decision.

        Default bumped 1h → 24h (2026-04-25) — a 1h timeout falling
        through to "timeout" → fall-through-to-stop violates the
        never-die contract: the user being AFK shouldn't terminate
        their run. The FE watchdog T3 catches genuinely-dead runs via
        silence detection; this timeout is now effectively a no-op
        backstop. BE keeps heartbeating in the await loop so the
        watchdog stays alive while paused for user decision."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self.stop_event.is_set():
                return "stop"
            if self.consume_retry_phase(phase):
                return "retry"
            if self.consume_phase_skip(phase):
                return "skip"
            await asyncio.sleep(0.5)
        return "timeout"

    def request_retry_agent(self, agent: str):
        """User clicked 'Retry [Agent]' on a Phase 2 agent warning."""
        key = (agent or "").strip().lower()
        if key:
            self.retry_agents.add(key)
            self.pause_event.clear()
            self.resume_event.set()

    def consume_retry_agent(self, agent: str) -> bool:
        key = (agent or "").strip().lower()
        if key in self.retry_agents:
            self.retry_agents.discard(key)
            return True
        return False

    def request_retry_agent_hard(self, agent: str):
        """Hard retry: close the agent's tab and re-run start_agent_no_gemini_wait
        from scratch. Preserves other agents; only this one gets a clean slate.
        Use when the soft follow-up can't recover (e.g., session expired, tab
        crashed, hostile Cloudflare gate)."""
        key = (agent or "").strip().lower()
        if key:
            self.retry_agents_hard.add(key)
            self.pause_event.clear()
            self.resume_event.set()

    def consume_retry_agent_hard(self, agent: str) -> bool:
        key = (agent or "").strip().lower()
        if key in self.retry_agents_hard:
            self.retry_agents_hard.discard(key)
            return True
        return False

    def request_continue_partial(self, agent: str):
        """User clicked 'Continue with partial' on a Phase 2 agent warning."""
        key = (agent or "").strip().lower()
        if key:
            self.continue_partial_agents.add(key)
            self.pause_event.clear()
            self.resume_event.set()

    def consume_continue_partial(self, agent: str) -> bool:
        key = (agent or "").strip().lower()
        if key in self.continue_partial_agents:
            self.continue_partial_agents.discard(key)
            return True
        return False

    def request_poke_agent(self, agent: str):
        """User clicked 'Poke [Agent]' on a stuck-agent warning. Phase 2 polling
        consumes this and submits a gentle "please continue" follow-up."""
        key = (agent or "").strip().lower()
        if key:
            self.poke_agents.add(key)
            self.pause_event.clear()
            self.resume_event.set()

    def consume_poke_agent(self, agent: str) -> bool:
        key = (agent or "").strip().lower()
        if key in self.poke_agents:
            self.poke_agents.discard(key)
            return True
        return False

    def request_wait_longer_agent(self, agent: str):
        """User clicked 'Wait longer' on a stuck-agent warning. Phase 2 polling
        resets the no-growth timer, granting another 10 min before re-prompting."""
        key = (agent or "").strip().lower()
        if key:
            self.wait_longer_agents.add(key)
            self.pause_event.clear()
            self.resume_event.set()

    def consume_wait_longer_agent(self, agent: str) -> bool:
        key = (agent or "").strip().lower()
        if key in self.wait_longer_agents:
            self.wait_longer_agents.discard(key)
            return True
        return False

    async def await_agent_decision(self, agent: str, timeout: float = 300.0) -> str:
        """Wait for user decision on a Phase 2 agent pipeline_warning
        offering [Retry] / [Wait] / [Skip]. Returns:
            'retry'            — retry this agent with a follow-up prompt
            'wait_longer'      — extend the polling budget without nudging
            'continue_partial' — accept current output and finalize (legacy
                                  command, still handled for backward compat)
            'skip'             — drop this agent entirely
            'stop'             — pipeline stopped
            'timeout'          — no decision in window (caller defaults to wait_longer)
        Polls every 0.5s. Skip is detected via existing skipped_agents set (NOT consumed here — the main Phase 2 loop handles the removal)."""
        key = (agent or "").strip().lower()
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self.stop_event.is_set():
                return "stop"
            if self.consume_retry_agent(key):
                return "retry"
            if self.consume_wait_longer_agent(key):
                return "wait_longer"
            if self.consume_continue_partial(key):
                return "continue_partial"
            if key in self.skipped_agents:
                return "skip"
            await asyncio.sleep(0.5)
        return "timeout"

    def consume_phase_skip(self, phase: int) -> bool:
        """Check + clear the skip flag for this phase. True when a skip was
        queued; consuming it here ensures a subsequent phase doesn't inherit
        the flag."""
        try:
            p = int(phase)
        except (TypeError, ValueError):
            return False
        if p in self.skipped_phases:
            self.skipped_phases.discard(p)
            return True
        return False

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
        self.agent_chat_urls: dict = {}  # platform → URL (conversation/chat)
        # Public share / canonical export URLs for each P2 agent — populated
        # in extract_and_record_agent (Commit 11) by an inline best-effort
        # extractor. Falls back silently to the conversation URL when public
        # share extraction fails. Phase 5 (Google Doc) prefers this over
        # agent_chat_urls so the doc carries proper shareable links.
        # Shape: {platform: {"url": str, "kind": "public"|"conversation",
        #                    "label": str, "verified": bool}}
        self.agent_share_urls: dict = {}
        self.partial_text_lens: dict = {}
        self.original_inputs: dict = {}  # {'topic': str, 'brief': str, 'pdf_paths': []}
        self.queue_dir = None
        self.browser = None
        self.cua_client = None
        self.dispatcher_task = None
        # Mid-phase restart signal: set when a paused phase resumes with buffered
        # extra_context. Caller coroutines check this and bail out early so the
        # orchestrator can re-run the phase with the combined input.
        self.restart_requested = False
        # 2026-04-26: Claude artifact panel kept-open flag (commit d45807f).
        # Polling sets True after first artifact open; extract_claude_response
        # reads via getattr to decide whether to close-first before clicking the
        # final artifact. Initialized here so reset() always lands at False
        # (otherwise an attribute set externally would leak across runs).
        self.claude_artifact_panel_open = False

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


# ── Platform login markers + root URLs (used by verify_login + setup) ────
#
# Each entry maps a platform key (matching the ones emitted to the frontend)
# to the minimum set of DOM signals that confirm a logged-in session. The
# first marker is checked via Playwright's fast `locator.count()` — a non-zero
# count means logged in. If all markers miss, we fall back to the URL/form
# check from `check_auth()`.
#
# Keep selectors LOOSE — they should survive minor UI tweaks. We care about
# "is this user authenticated" not "is a specific button present".

# Fast-path auth-cookie signatures — used by cookie_login_hit() to skip
# expensive tab-open + CUA verify when the profile already holds a
# likely-valid session. Presence check only; expiry is respected when
# set. A miss means "not sure, go verify properly" — a hit short-
# circuits to "logged in" for probe/setup paths. Phase 0 preflight
# (the one source-of-truth check) still runs full CUA even on a hit
# because we don't want false positives corrupting the gate that
# every subsequent phase trusts.
_AUTH_COOKIE_SIGNATURES = {
    "chatgpt":    {"names": ["__Secure-next-auth.session-token"],
                   "domains": ["chatgpt.com", "openai.com"]},
    "gemini":     {"names": ["__Secure-1PSID", "__Secure-3PSID"],
                   "domains": ["google.com"]},
    "notebooklm": {"names": ["__Secure-1PSID", "__Secure-3PSID"],
                   "domains": ["google.com"]},
    "youtube":    {"names": ["__Secure-1PSID", "__Secure-3PSID"],
                   "domains": ["google.com", "youtube.com"]},
    "gmail":      {"names": ["__Secure-1PSID", "__Secure-3PSID"],
                   "domains": ["google.com"]},
    "gdocs":      {"names": ["__Secure-1PSID", "__Secure-3PSID"],
                   "domains": ["google.com"]},
    "claude":     {"names": ["sessionKey"],
                   "domains": ["claude.ai"]},
}


async def cookie_login_hit(browser_or_context, key: str) -> bool:
    """Return True when the profile holds a cookie matching the platform's
    auth signature (primary session token on the right domain, non-expired).
    Callers treat True as 'skip the CUA/DOM verify — already logged in';
    False means 'not sure' so they fall through to the full check. Cheap:
    no network, no tab-open, no CUA spend.

    Accepts either a Browser instance or a raw BrowserContext."""
    sig = _AUTH_COOKIE_SIGNATURES.get(key)
    if not sig:
        return False
    ctx = getattr(browser_or_context, "context", browser_or_context)
    if ctx is None:
        return False
    try:
        cookies = await ctx.cookies()
    except Exception:
        return False
    now = time.time()
    want_names = set(sig["names"])
    want_hosts = sig["domains"]
    for c in cookies:
        if c.get("name") not in want_names:
            continue
        domain = (c.get("domain") or "").lstrip(".")
        if not any(domain == h or domain.endswith("." + h) for h in want_hosts):
            continue
        exp = c.get("expires", -1)
        # -1 = session cookie (persists per browser-session — good enough).
        # Any other value is unix seconds; accept if still in the future.
        if exp == -1 or exp > now:
            return True
    return False


LOGIN_PLATFORMS = {
    # Markers must be AUTH-SPECIFIC: profile menus, account chips, chat history
    # lists, compose buttons. Never use generic input elements (textarea,
    # rich-textarea) — those appear on logged-out landing pages too and cause
    # false positives. We list MULTIPLE markers per platform to be resilient
    # to UI drift; verify_login() matches if ANY selector is present.
    "chatgpt":    {"root": "https://chatgpt.com/", "markers": [
        'button[data-testid="profile-button"]',
        'button[aria-label="Open Profile Menu"]',
        'nav[aria-label="Chat history"]',
        'a[href="/gpts"]',
        'button[data-testid="create-new-chat-button"]',
        'aside[class*="sidebar"] a[href*="/c/"]',  # existing chat links in sidebar
    ]},
    "gemini":     {"root": "https://gemini.google.com/app", "markers": [
        'a[aria-label*="Google Account"]',
        '.gb_d[aria-label*="Google Account"]',
        'bard-sidenav',
        'button[aria-label*="New chat"]',
        'side-navigation-v2',
        'button[aria-label*="Sign out"]',
    ]},
    "claude":     {"root": "https://claude.ai/chats", "markers": [
        'button[data-testid="user-menu-button"]',
        'button[aria-label*="account"]',
        'div[data-testid="chat-list"]',
        'a[data-testid="starter-prompt"]',
        'button[aria-label*="New Chat"]',
        'nav a[href*="/recents"]',
    ]},
    "notebooklm": {"root": "https://notebooklm.google.com/", "markers": [
        'a[aria-label*="Google Account"]',
        'project-button',
        'create-new-button',
        'button[aria-label*="Create"]',
        '.mat-mdc-card-title',  # project cards on the home page
    ]},
    "youtube":    {"root": "https://studio.youtube.com/", "markers": [
        'ytcp-navigation-drawer',
        'ytcp-button[id="create-icon"]',
        'tp-yt-iron-icon[icon-id="channel-icon"]',
        'ytcp-entity-avatar',
        'tp-yt-paper-icon-button[aria-label*="Upload"]',
    ]},
    "gmail":      {"root": "https://mail.google.com/mail/", "markers": [
        'div[gh="cm"]',
        'a[aria-label*="Compose"]',
        'div[role="main"][data-tab-id]',
        'div[jsname][gh="mtb"]',  # mail toolbar
        'a[aria-label*="Gmail"][role="button"]',
    ]},
    "gdocs":      {"root": "https://docs.google.com/document/u/0/", "markers": [
        'a[aria-label*="Google Account"]',
        '.docs-homescreen-gb-container',
        'c-wiz[data-p]',  # main content container (only post-auth)
        'div[role="main"][aria-label*="Docs home"]',
    ]},
}


async def verify_login(page, platform: str, *, ensure_nav: bool = False, nav_timeout: int = 15000, strict: bool = False) -> bool:
    """Verify the platform session is authenticated on the given page.

    Checks (in order):
      1. Any of the platform's DOM markers is present (fast, deterministic).
      2. Negative-signal check: visible Sign in / Log in button OR password
         input field → returns False.
      3. Ambiguous (no positive markers + no negative signals):
         - strict=False (pipeline path, default): fail-OPEN → return True and
           let downstream check_auth() catch real session failures. Tolerant
           of DOM selector drift after the user has already completed setup.
         - strict=True (setup path): fail-CLOSED → return False. Used by
           --pair step 3 where the entire point is to wait until the user
           actually logs in; we cannot let a persistent browser profile with
           partial state fool setup into auto-advancing.

    When `ensure_nav=True`, navigates to the platform root before checking so
    callers don't have to set up the URL themselves.
    """
    info = LOGIN_PLATFORMS.get(platform.lower())
    if not info:
        return False  # Unknown platform — fail closed

    try:
        if ensure_nav:
            try:
                await page.goto(info["root"], wait_until="domcontentloaded", timeout=nav_timeout)
            except Exception:
                pass
            # Small settle so SPA hydration paints the nav
            await asyncio.sleep(1.5)

        # If URL is obviously a login URL, short-circuit to False
        try:
            current = (page.url or "").lower()
        except Exception:
            current = ""
        login_hosts = ("auth.openai.com", "accounts.google.com/signin", "login.live.com", "claude.ai/login", "claude.ai/signup")
        for h in login_hosts:
            if h in current:
                return False

        # DOM marker check — any positive match means logged in.
        for sel in info["markers"]:
            try:
                loc = page.locator(sel)
                cnt = await loc.count()
                if cnt > 0:
                    return True
            except Exception:
                continue

        # Negative signals — presence of a password input OR a prominent
        # "Sign in / Log in" button means NOT logged in.
        try:
            has_negative = await page.evaluate("""() => {
                if (document.querySelector('input[type="password"]')) return true;
                const LOGIN_RE = /^\\s*(sign\\s*in|log\\s*in|log\\s*on|continue with google)\\s*$/i;
                const buttons = document.querySelectorAll('button, a[role="button"], a');
                for (const b of buttons) {
                    const t = (b.textContent || '').trim();
                    if (!t || t.length > 40) continue;
                    if (!LOGIN_RE.test(t)) continue;
                    const r = b.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && r.top < window.innerHeight) return true;
                }
                return false;
            }""")
            if has_negative:
                return False
        except Exception:
            pass

        # Ambiguous — no positive markers, no negative signals. Split based
        # on caller context:
        #   strict=True (setup step 3): fail-CLOSED — we need to WAIT until
        #     the user actually logs in; auto-advancing would defeat setup.
        #   strict=False (pipeline runs): fail-OPEN — don't trap the user on
        #     drifted selectors when check_auth() will catch real failures.
        if strict:
            log(f"[verify_login:strict] {platform}: no login markers yet — waiting", "INFO")
            return False
        log(f"[verify_login] {platform}: ambiguous (no markers + no negative signals) — assuming logged in", "WARN")
        return True
    except Exception as e:
        log(f"[verify_login] {platform}: {e}", "WARN")
        return False


# Structural CUA failures (billing cap, invalid key, overload) are raised
# as this exception so callers can distinguish them from a legitimate
# login-wall NO verdict. See _cua_login_call for the matched error patterns.
class CuaUnavailableError(RuntimeError):
    pass


# Human-readable platform names used when prompting CUA for login verification.
# Keep these descriptive so the model knows which brand/site to identify.
_PLATFORM_DISPLAY = {
    "chatgpt":    "ChatGPT (chatgpt.com)",
    "gemini":     "Google Gemini (gemini.google.com)",
    "claude":     "Claude (claude.ai)",
    "notebooklm": "Google NotebookLM (notebooklm.google.com)",
    "youtube":    "YouTube Studio (studio.youtube.com)",
    "gmail":      "Gmail (mail.google.com)",
    "gdocs":      "Google Docs (docs.google.com)",
}


async def _cua_login_call(page, platform: str, cua_client) -> tuple[bool, str]:
    """Single CUA vision call. Returns (verdict_yes, raw_response)."""
    display = _PLATFORM_DISPLAY.get(platform.lower(), platform)
    try:
        buf = await page.screenshot(type="png", timeout=10000, full_page=False)
        b64 = base64.b64encode(buf).decode("ascii")
    except Exception as e:
        log(f"[verify_login_cua:{platform}] screenshot failed: {e}", "WARN")
        return (False, f"screenshot error: {e}")

    # Tight, positive-leaning prompt. We want YES when the authenticated app
    # UI is visible even if some secondary login-looking affordance exists.
    # False positives on modals/login walls are an order of magnitude worse
    # than false negatives — but false negatives (logged-in user shown as
    # logged-out) break the pipeline flow entirely, so we bias YES.
    prompt = (
        f"Screenshot of {display}.\n\n"
        f"Say YES if the authenticated app is visible and usable — e.g., "
        f"a chat composer, sidebar with user's own history, inbox with "
        f"messages, project/doc list, profile avatar, or any other UI "
        f"that only appears AFTER sign-in.\n\n"
        f"Say NO ONLY if the main content is clearly a login wall: a "
        f"centered sign-in form with a password field, a Google account "
        f"picker at accounts.google.com, or a marketing landing page "
        f"where the dominant action is \"Log in\" / \"Sign up\".\n\n"
        f"A transient loading spinner, a cookie banner, a sidebar nav "
        f"link labelled \"Log in\" on an otherwise-authenticated page, "
        f"or a small upsell popup do NOT count as a login wall — answer "
        f"YES in those cases.\n\n"
        f"Reply with ONLY one word: YES or NO."
    )
    try:
        resp = await asyncio.to_thread(
            cua_client.messages.create,
            model=CUA_MODEL,
            max_tokens=8,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw = ""
        try:
            for blk in resp.content:
                if getattr(blk, "type", None) == "text":
                    raw = (blk.text or "").strip()
                    break
        except Exception:
            raw = ""
        verdict = raw.strip().lower()
        return (verdict.startswith("yes"), raw or "")
    except Exception as e:
        # Distinguish structural API failures (billing cap, invalid key,
        # overload) from a genuine login-wall NO. The caller treats a
        # False verdict as "not logged in" and prompts the user to log
        # in — but if the REAL blocker is an Anthropic 400/401/529, the
        # user chasing a phantom auth issue wastes their time. We surface
        # those errors as an exception so Phase 0 can emit a dedicated
        # pipeline_error ("CUA unavailable — [Skip] [Stop]") instead of
        # spinning on login_required.
        err = str(e)
        low = err.lower()
        if ("workspace api usage limits" in low
            or ("400" in err and "usage limit" in low)
            or ("401" in err and ("unauthorized" in low or "invalid" in low or "api_key" in low))
            or "overloaded" in low or "529" in err):
            raise CuaUnavailableError(err) from e
        return (False, f"API error: {e}")


async def verify_login_cua(page, platform: str, cua_client) -> bool:
    """Vision-based login verification with a two-strike retry.

    DOM selectors drift and some platforms show auth-like markers (New chat,
    sidebar nav) even on the logged-out landing page. Vision is the only
    reliable way to tell "modal/login wall" from "authenticated app".

    Strategy: one quick check → if NO, wait 3s (lets Claude.ai / Gemini /
    Google Docs finish hydrating) and re-check once. Only flag as not
    logged in if BOTH checks disagree. Eliminates false positives from
    transient loading states while still catching real logout walls.

    Returns True iff at least one of the checks clearly says YES.
    """
    ok1, raw1 = await _cua_login_call(page, platform, cua_client)
    if ok1:
        log(f"[verify_login_cua:{platform}] LOGGED IN ✓ (Claude: {raw1[:30]})", "INFO")
        return True

    # Second attempt — let the page hydrate a bit more and re-check. Some
    # SPAs (claude.ai/chats, docs.google.com) paint a neutral "loading"
    # state for the first 3-4s that CUA misreads as a login wall.
    log(f"[verify_login_cua:{platform}] first pass said NO ({raw1[:30]}) — re-checking after settle", "INFO")
    try:
        await asyncio.sleep(3.5)
        # Kick a tiny scroll so lazy-hydrated UI paints (harmless if page ignores).
        try:
            await page.evaluate("() => window.scrollBy(0, 0)")
        except Exception:
            pass
    except Exception:
        pass
    ok2, raw2 = await _cua_login_call(page, platform, cua_client)
    if ok2:
        log(f"[verify_login_cua:{platform}] LOGGED IN ✓ on retry (Claude: {raw2[:30]})", "INFO")
        return True

    log(f"[verify_login_cua:{platform}] NOT LOGGED IN ✗ (Claude both passes: '{raw1[:20]}' / '{raw2[:20]}')", "INFO")
    return False


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

# ── Link Validation — single source of truth for URL correctness ─────────────

# Per-platform patterns that indicate a REAL public/shareable link (not a page URL)
_LINK_VALIDATORS = {
    "chatgpt": lambda u: "chatgpt.com/share/" in u,
    "gemini":  lambda u: ("gemini.google.com/share" in u or "g.co/gemini" in u),
    "claude":  lambda u: ("claude.site/artifacts/" in u or "claude.site/" in u),
    "notebooklm": lambda u: "notebooklm.google.com/notebook/" in u,
    "youtube": lambda u: ("youtu.be/" in u or "youtube.com/watch?v=" in u),
    "gdocs":   lambda u: "docs.google.com/document/" in u,
}

# Known BAD URLs that must NEVER be emitted as links
_BAD_URL_PATTERNS = [
    "studio.youtube.com",       # YouTube Studio (not a video link)
    "chatgpt.com/c/",           # ChatGPT conversation (not shared)
    "chatgpt.com/?model",       # ChatGPT home
    "gemini.google.com/app",    # Gemini app (not shared)
    "claude.ai/new",            # Claude new chat
    "claude.ai/chat/",          # Claude conversation (not published artifact)
    "mail.google.com",          # Gmail (not a doc)
    "accounts.google.com",      # Auth page
]


def validate_link(platform: str, url: str) -> bool:
    """Check if a URL is a REAL shareable link for the given platform.
    Returns False for page URLs, studio URLs, and other non-shareable URLs."""
    if not url or not url.startswith("http"):
        return False
    # Reject known bad patterns
    for bad in _BAD_URL_PATTERNS:
        if bad in url:
            return False
    # Check platform-specific validator
    validator = _LINK_VALIDATORS.get(platform.lower().replace(" ", ""))
    if validator:
        return validator(url)
    # Unknown platform — reject to prevent bad URLs from leaking through
    log(f"validate_link: unknown platform '{platform}' — rejecting {url[:60]}", "WARN")
    return False


def emit_validated_link(phase: int, agent: str, url: str, label: str):
    """Emit a link_extracted event ONLY if the URL passes validation.
    Returns True if emitted, False if rejected."""
    verified = validate_link(agent, url)
    if not verified:
        log(f"[{label}] Link REJECTED — not a valid public link: {url[:80]}", "WARN")
        emit_event("link_extraction_failed", phase=phase, agent=agent,
                   error=f"URL is not a valid public link: {url[:60]}")
        return False
    emit_event("link_extracted", phase=phase, agent=agent,
               url=url, label=label, verified=True)
    log(f"[{label}] Link VERIFIED: {url}")
    return True


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
    """Extract shareable ChatGPT link: Share button → Create link → copy URL.

    Iframe short-circuit (2026-04): ChatGPT Deep Research renders inside a
    cross-origin sandbox iframe that often intercepts pointer events on the
    host Share button. Default Playwright click retries for 30s per attempt
    and then throws. We use a 3s click timeout so the iframe-intercept path
    fails fast — the caller (extract_and_record_agent) then falls back to
    the chat URL without burning 90s across retries."""
    page = browser.page
    url = await browser.current_url() or ""
    try:
        # 2026-04-26: close-first preamble — any open citations panel,
        # plan-item drawer, or modal can intercept the Share button click.
        # Mirror of Claude's pattern at the top of extract_share_link_claude.
        try:
            await page.evaluate("""() => {
                const close = document.querySelector(
                    '[role="dialog"] button[aria-label*="Close"], ' +
                    '[role="dialog"] button[aria-label*="close"], ' +
                    'button[aria-label*="Close panel"], ' +
                    'button[aria-label*="Close sources"]'
                );
                if (close) close.click();
            }""")
            await asyncio.sleep(0.5)
        except Exception:
            pass
        # Step 1: Try Playwright — find share button
        share_btn = None
        for sel in ['button[aria-label="Share"]', '[data-testid="share-chat-button"]',
                    'button:has(svg[data-testid="share-icon"])']:
            share_btn = await page.query_selector(sel)
            if share_btn:
                break
        if share_btn:
            # Short-timeout click — iframe intercepts surface as timeout here,
            # and we want to abort the public-share path immediately rather
            # than waste 30s per retry attempt.
            try:
                await share_btn.click(timeout=3000)
            except Exception as _ce:
                log(f"[{label}] Share click short-circuited ({_ce}) — public-link fast-fail", "WARN")
                return LinkResult(url=url, label=label, platform="chatgpt",
                                  verified=False, error=f"share_click_intercept: {_ce}")
            await asyncio.sleep(2)
            # Look for "Create link" or "Copy link" button in modal
            link_btn = None
            for sel in ['button:has-text("Create link")', 'button:has-text("Copy link")',
                        'button:has-text("Share")', '[data-testid="share-link-button"]']:
                link_btn = await page.query_selector(sel)
                if link_btn:
                    break
            if link_btn:
                try:
                    await link_btn.click(timeout=3000)
                except Exception as _ce2:
                    log(f"[{label}] Create/Copy link click short-circuited ({_ce2})", "WARN")
                    return LinkResult(url=url, label=label, platform="chatgpt",
                                      verified=False, error=f"link_click_intercept: {_ce2}")
                await asyncio.sleep(2)
            # PRIMARY — try to get URL from input field in modal
            share_input = await page.query_selector('input[readonly][value*="chatgpt.com/share"]')
            if share_input:
                url = await share_input.get_attribute("value") or url
            # SECONDARY — read the browser's clipboard directly (the "Copy link"
            # button wrote the public /share/ URL into it). This is far more
            # reliable than asking CUA to recover it via screenshots.
            # 2s wait_for: a clipboard permission prompt or a busy clipboard
            # used to hang this evaluate() indefinitely on Windows.
            if "chatgpt.com/share" not in url:
                try:
                    clip_js = await asyncio.wait_for(
                        page.evaluate("navigator.clipboard.readText()"),
                        timeout=2.0,
                    )
                    if clip_js and "chatgpt.com/share" in clip_js:
                        url = clip_js.strip()
                        log(f"[{label}] Share URL recovered from browser clipboard: {url}")
                except (asyncio.TimeoutError, Exception):
                    # clipboard-read permission may be denied / hung; fall through
                    pass
            # TERTIARY — Windows OS clipboard via PowerShell. PowerShell can
            # block on a locked clipboard (antivirus / another process holding
            # it); cap with a 3s deadline so the pipeline doesn't stall.
            if "chatgpt.com/share" not in url:
                try:
                    clip = await asyncio.wait_for(
                        asyncio.to_thread(get_clipboard),
                        timeout=3.0,
                    )
                    if "chatgpt.com/share" in (clip or ""):
                        url = clip
                except (asyncio.TimeoutError, Exception):
                    pass
            # Close modal
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        # Step 2: CUA fallback if no share URL yet. Hard-cap at 120s — the
        # agent_loop's max_iterations=6 doesn't bound wall-clock time, so a
        # stuck CUA could loiter for many minutes. The wait_for keeps the
        # share-link path bounded and reachable.
        if "chatgpt.com/share" not in url:
            log(f"[{label}] CUA fallback for share link...")
            try:
                result = await asyncio.wait_for(
                    agent_loop(cua_client, browser,
                        "Share this ChatGPT conversation by clicking the Share button.",
                        "Click the Share button at the top of this conversation. If a modal appears, click 'Create link' or 'Copy link'. After clicking Copy link, just STOP — don't try to extract the URL yourself, the code will read it from the clipboard.",
                        model=CUA_MODEL, max_iterations=6, verbose=verbose),
                    timeout=120.0,
                )
            except asyncio.TimeoutError:
                log(f"[{label}] CUA share-link extraction timed out (120s) — using current URL as fallback", "WARN")
                result = {"text": ""}
            text = (result.get("text") or "")
            # Extract URL from CUA response (if it happened to observe one)
            m = re.search(r'https://chatgpt\.com/share/[a-zA-Z0-9-]+', text)
            if m:
                url = m.group(0)
            # After CUA clicked "Copy link", read the browser clipboard directly
            if "chatgpt.com/share" not in url:
                try:
                    clip_js = await asyncio.wait_for(
                        page.evaluate("navigator.clipboard.readText()"),
                        timeout=2.0,
                    )
                    if clip_js and "chatgpt.com/share" in clip_js:
                        url = clip_js.strip()
                        log(f"[{label}] Share URL recovered from clipboard after CUA share click: {url}")
                except (asyncio.TimeoutError, Exception):
                    pass
            if "chatgpt.com/share" not in url:
                try:
                    clip = await asyncio.wait_for(
                        asyncio.to_thread(get_clipboard),
                        timeout=3.0,
                    )
                    if "chatgpt.com/share" in (clip or ""):
                        url = clip
                except (asyncio.TimeoutError, Exception):
                    pass
        verified = "chatgpt.com/share" in url
        return LinkResult(url=url, label=label, platform="chatgpt", verified=verified)
    except Exception as e:
        log(f"Link extraction failed (ChatGPT): {e}", "WARN")
        return LinkResult(url=url, label=label, platform="chatgpt", error=str(e))


async def extract_share_link_gemini(browser, cua_client, label="Gemini Deep Research", verbose=False):
    """Extract shareable Gemini conversation link with public visibility.

    Hardened 2026-04-25:
    - Added "Export & save" label variants (current Gemini Deep Research
      UI sometimes uses this instead of "Share & Export").
    - Wrapped the CUA fallback in a 90 s timeout so a stuck CUA loop can't
      starve the inline 90 s outer budget at the call-site.
    - Structured error attribution: errors are tagged in `LinkResult.error`
      with a short stage tag (`open_dialog` / `public_toggle` / `link_lookup`
      / `cua_fallback`) so operators can see *where* the flow failed.
    """
    page = browser.page
    url = await browser.current_url() or ""
    last_stage = "init"
    try:
        # 2026-04-26: close-first preamble — close any open dialog/drawer
        # that could intercept the Share & Export click. Same pattern as
        # Claude (extract_share_link_claude) and ChatGPT.
        try:
            await page.evaluate("""() => {
                const close = document.querySelector(
                    '[role="dialog"] button[aria-label*="Close"], ' +
                    '[role="dialog"] button[aria-label*="close"], ' +
                    'button[aria-label*="Close panel"], ' +
                    'mat-dialog-container button[aria-label*="Close"]'
                );
                if (close) close.click();
            }""")
            await asyncio.sleep(0.5)
        except Exception:
            pass
        # ── Open the share/export dialog ──
        # Current Gemini Deep Research UI variants seen:
        #   - "Share & Export" (post-2025 redesign)
        #   - "Share and export" (a11y-label variant)
        #   - "Export & save"   (newer 2026 redesign — added 2026-04-25)
        #   - "Share"           (legacy)
        # Try aria-label exact matches first, then partial matches, then
        # fall through to a text-content scan for variants without an
        # aria-label at all.
        last_stage = "open_dialog"
        share_opened = False
        for sel in [
            'button[aria-label="Share & Export"]',
            'button[aria-label="Share and export"]',
            'button[aria-label="Export & save"]',
            'button[aria-label="Export and save"]',
            'button[aria-label*="Share & Export"]',
            'button[aria-label*="Share and export"]',
            'button[aria-label*="Export & save"]',
            'button[aria-label*="Export and save"]',
            'button[aria-label="Share"]',
            'button[aria-label*="Share"]',
        ]:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    share_opened = True
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue
        if not share_opened:
            try:
                clicked = await page.evaluate("""() => {
                    const btns = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null);
                    const target = btns.find(b => {
                        const t = (b.textContent || '').trim().toLowerCase();
                        return t === 'share & export' || t === 'share and export' ||
                               t === 'export & save' || t === 'export and save' ||
                               t === 'share';
                    });
                    if (target) { target.click(); return true; }
                    return false;
                }""")
                if clicked:
                    share_opened = True
                    await asyncio.sleep(2)
            except Exception:
                pass
        if share_opened:
            # "Share & Export" / "Export & save" opens a submenu (Create
            # public link / Export to Docs / Copy). Click the public-link
            # option before the link lookup, otherwise we land on the Export
            # flow.
            last_stage = "public_toggle"
            try:
                await page.evaluate("""() => {
                    const items = [...document.querySelectorAll(
                        '[role="menuitem"], [role="option"], button, li, a'
                    )].filter(el => el.offsetParent !== null);
                    const target = items.find(el => {
                        const t = (el.textContent || '').trim().toLowerCase();
                        return t === 'create public link' ||
                               t === 'public link' ||
                               t.includes('create public link') ||
                               t.includes('create a public link');
                    });
                    if (target) target.click();
                }""")
                await asyncio.sleep(1.5)
            except Exception:
                pass

            # ── Ensure public visibility ("Anyone with the link") ──
            # Gemini share dialog may default to Restricted — click through to public
            try:
                visibility_set = await page.evaluate("""() => {
                    // Strategy 1: Look for dropdown/button showing "Restricted" or "Only people"
                    const btns = document.querySelectorAll(
                        'button, [role="button"], [role="combobox"], [aria-haspopup]'
                    );
                    for (const btn of btns) {
                        const txt = (btn.innerText || btn.textContent || '').toLowerCase();
                        if (txt.includes('restricted') || txt.includes('only people')) {
                            btn.click();
                            return 'opened_dropdown';
                        }
                    }
                    // Strategy 2: Look for "Enable sharing" toggle
                    const toggles = document.querySelectorAll(
                        'input[type="checkbox"], [role="switch"], [aria-checked]'
                    );
                    for (const t of toggles) {
                        const label = (t.closest('label') || t.parentElement);
                        const txt = (label?.innerText || '').toLowerCase();
                        if (txt.includes('share') || txt.includes('public') || txt.includes('anyone')) {
                            if (t.getAttribute('aria-checked') === 'false' || !t.checked) {
                                t.click();
                                return 'toggled_on';
                            }
                            return 'already_on';
                        }
                    }
                    return '';
                }""")
                if visibility_set == 'opened_dropdown':
                    await asyncio.sleep(1)
                    # Select "Anyone with the link" from the dropdown
                    await page.evaluate("""() => {
                        const options = document.querySelectorAll(
                            '[role="option"], [role="menuitem"], [role="menuitemradio"], li'
                        );
                        for (const opt of options) {
                            const txt = (opt.innerText || opt.textContent || '').toLowerCase();
                            if (txt.includes('anyone with the link') || txt.includes('anyone')) {
                                opt.click();
                                return 'selected';
                            }
                        }
                        return '';
                    }""")
                    await asyncio.sleep(1)
                    log(f"[{label}] Set sharing to 'Anyone with the link'")
            except Exception as e:
                log(f"[{label}] Visibility selection attempt: {e}", "WARN")

            # Look for shareable link in modal
            last_stage = "link_lookup"
            link_el = await page.query_selector('input[value*="g.co/gemini"]')
            if not link_el:
                link_el = await page.query_selector('input[value*="gemini.google.com/share"]')
            if link_el:
                url = await link_el.get_attribute("value") or url
            else:
                # Try clicking "Copy link" button
                try:
                    await page.evaluate("""() => {
                        const btns = document.querySelectorAll('button');
                        for (const b of btns) {
                            const txt = (b.innerText || '').toLowerCase();
                            if (txt.includes('copy link') || txt.includes('copy')) {
                                b.click();
                                return 'copied';
                            }
                        }
                        return '';
                    }""")
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
                clip = get_clipboard()
                if "gemini" in clip and "share" in clip:
                    url = clip
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        if "share" not in url.lower():
            # CUA fallback — explicit public sharing instructions, capped at
            # 90 s. Without the cap, an outer 90 s budget at the call-site
            # (extract_and_record_agent inline share extraction) could be
            # consumed entirely by a stuck CUA loop and still time out, with
            # the page never getting to even check the clipboard.
            last_stage = "cua_fallback"
            try:
                result = await asyncio.wait_for(
                    agent_loop(cua_client, browser,
                        PROMPT_SHARE_GEMINI,
                        "Click the Share button for this Gemini conversation. "
                        "IMPORTANT: Change the access to 'Anyone with the link' (not Restricted). "
                        "Then copy the shareable link and tell me the EXACT URL "
                        "(g.co/gemini/... or gemini.google.com/share/...).",
                        model=CUA_MODEL, max_iterations=12, verbose=verbose),
                    timeout=90.0,
                )
                m = re.search(r'https://[^\s]+gemini[^\s]*share[^\s]*', (result.get("text") or ""))
                if not m:
                    m = re.search(r'https://g\.co/gemini/[^\s]+', (result.get("text") or ""))
                if m:
                    url = m.group(0)
                else:
                    clip = get_clipboard()
                    if clip and ("gemini" in clip or "g.co" in clip) and "share" in clip:
                        url = clip
            except asyncio.TimeoutError:
                log(f"[{label}] CUA fallback exceeded 90s — using best-effort URL", "WARN")
                # Salvage: maybe CUA copied to clipboard before the timeout.
                clip = get_clipboard()
                if clip and ("gemini" in clip or "g.co" in clip) and "share" in clip:
                    url = clip
        # Tight public-link gate: Gemini's Share & Export flow produces URLs on
        # gemini.google.com/share/ or g.co/gemini/... — require one of those
        # explicitly so that a stale chat URL (gemini.google.com/app/...) or a
        # share-dialog URL never sneaks through as verified. The Phase 2 outer
        # loop will fall back to the chat URL silently with verified=False when
        # this gate fails.
        _lu = url.lower()
        verified = ("gemini.google.com/share" in _lu) or ("g.co/gemini" in _lu)
        return LinkResult(url=url, label=label, platform="gemini", verified=verified)
    except Exception as e:
        return LinkResult(url=url, label=label, platform="gemini",
                          error=f"{last_stage}: {type(e).__name__}: {e}")


async def extract_share_link_claude(browser, cua_client, label="Claude Deep Research", verbose=False):
    """Extract shareable Claude artifact link.

    Hardened 2026-04-25:
    - **Close first, open last**: Claude conversations with multiple
      artifacts can leave a non-final artifact panel open after content
      extraction (e.g. the early "research plan" artifact, with the real
      deep-research output written to a SECOND artifact below it). The
      `publish_open_claude_artifact` primary path publishes whatever's
      open — if that's the wrong one, the URL we return points at the
      plan, not the report. Explicit close-1st-then-open-last sequence
      forces the correct selection before publishing.
    - **90 s CUA cap**: the CUA fallback is wrapped in asyncio.wait_for so
      a stuck CUA loop can't blow the inline 90 s outer budget.
    - **Stage-tagged errors** for operator visibility.
    """
    page = browser.page
    url = await browser.current_url() or ""
    last_stage = "init"
    try:
        # Step 1: close any currently-open artifact panel and open the
        # LAST artifact in the conversation (the deep-research output).
        last_stage = "select_last_artifact"
        try:
            await page.evaluate("""() => {
                // Close any open artifact panel first.
                const closeBtn = document.querySelector(
                    'aside button[aria-label*="Close"], aside button[aria-label*="close"]'
                );
                if (closeBtn) closeBtn.click();
            }""")
            await asyncio.sleep(0.5)
            opened = await page.evaluate("""() => {
                // Find all artifact-preview tiles in the conversation, click the LAST one.
                // Selectors target the inline cards that open the right-side artifact panel.
                const candidates = document.querySelectorAll(
                    '[data-testid*="artifact"], button[aria-label*="Open artifact"], ' +
                    'button[aria-label*="open artifact"], a[href*="/artifacts/"], ' +
                    '[class*="artifact-preview"], [class*="ArtifactPreview"]'
                );
                if (candidates.length === 0) return 'no_artifacts';
                const last = candidates[candidates.length - 1];
                // Some preview cards aren't directly clickable — fall through to
                // a clickable ancestor (button or [role="button"]).
                const target = last.closest('button, [role="button"]') || last;
                target.click();
                return 'opened_last';
            }""")
            if opened == 'opened_last':
                # Let the artifact panel render before publish_open_claude_artifact
                # tries to find its publish/share button.
                await asyncio.sleep(1.5)
        except Exception as _ce:
            log(f"[{label}] artifact-select prelude skipped: {_ce}", "DEBUG")

        # Primary: try publishing via the (now correctly-selected) artifact panel
        last_stage = "publish_dom"
        published_url = await publish_open_claude_artifact(page, browser, cua_client, verbose=verbose)
        if published_url and 'claude.' in published_url:
            url = published_url
        else:
            # Fallback: full CUA flow, capped at 90s so a stuck loop doesn't
            # blow the inline 90s outer budget at the call-site.
            last_stage = "cua_fallback"
            try:
                result = await asyncio.wait_for(
                    agent_loop(cua_client, browser,
                        PROMPT_PUBLISH_CLAUDE,
                        "Publish the research ARTIFACT in the right panel (not the conversation). "
                        "If two artifacts exist, open the SECOND/bottom one first. "
                        "Click the Publish/Share icon on the artifact. "
                        "Get the published URL (claude.site/artifacts/... or claude.ai/...). "
                        "Tell me the URL.",
                        model=CUA_MODEL, max_iterations=12, verbose=verbose),
                    timeout=90.0,
                )
                text = (result.get("text") or "")
                m = re.search(r'https://claude\.(?:site|ai)/[^\s]+', text)
                if m:
                    url = m.group(0)
                else:
                    clip = get_clipboard()
                    if clip and "claude." in clip:
                        url = clip
            except asyncio.TimeoutError:
                log(f"[{label}] CUA fallback exceeded 90s — using best-effort URL", "WARN")
                clip = get_clipboard()
                if clip and "claude." in clip:
                    url = clip
        # Tight public-link gate: Claude has a reliable Publish flow, so only a
        # claude.site/ URL counts as verified. A bare claude.ai/chat/... URL is
        # the user's own chat (not a public share) — the Phase 2 outer loop will
        # fall back to it silently with verified=False when this gate fails.
        verified = "claude.site" in url.lower()
        return LinkResult(url=url, label=label, platform="claude", verified=verified)
    except Exception as e:
        return LinkResult(url=url, label=label, platform="claude",
                          error=f"{last_stage}: {type(e).__name__}: {e}")


async def _set_nlm_public_and_get_link(page, label):
    """Shared helper: inside an open NotebookLM share dialog,
    set Notebook access → 'Anyone with the link', copy/get the link, click Save.

    Returns a tuple (url, public_verified) — `public_verified` is True only
    when the dialog DOM confirms the access dropdown reads "Anyone with the
    link" before save. NotebookLM private and public URLs share the same
    `/notebook/{id}` shape, so URL format alone can't tell them apart — DOM
    verification is the only way to know the link is genuinely shareable.
    Phase 3's caller treats `public_verified=False` as a soft failure (still
    returns the URL so the run can continue, but logs prominently)."""
    url = ""
    public_verified = False
    try:
        # Step 1: Find "Notebook access" section and change to public
        # NLM share dialog shows "Notebook access" with a dropdown (not "Restricted")
        changed = await page.evaluate("""() => {
            // Look for clickable elements near "Notebook access" text
            const allText = document.body.innerText || '';
            // Find dropdown/button that controls access level
            const btns = document.querySelectorAll(
                'button, [role="button"], [role="combobox"], [role="listbox"], select, [aria-haspopup]'
            );
            for (const btn of btns) {
                const txt = (btn.innerText || btn.textContent || '').toLowerCase();
                const parentTxt = (btn.closest('div')?.innerText || '').toLowerCase();
                // NotebookLM uses "Notebook access" section; the dropdown shows current state
                if (txt.includes('restricted') || txt.includes('only people') ||
                    txt.includes('not shared') || txt.includes('private') ||
                    (parentTxt.includes('notebook access') && (txt.includes('off') || txt.length < 30))) {
                    btn.click();
                    return 'opened';
                }
            }
            // Also try: any element labeled "Notebook access" that's clickable
            const labels = document.querySelectorAll('label, span, div, h3, h4');
            for (const lbl of labels) {
                const txt = (lbl.innerText || '').toLowerCase();
                if (txt.includes('notebook access')) {
                    // Click the next sibling or the nearest button
                    const next = lbl.nextElementSibling || lbl.parentElement;
                    const btn = next?.querySelector('button, [role="button"], select');
                    if (btn) { btn.click(); return 'opened'; }
                }
            }
            return '';
        }""")
        if changed == 'opened':
            await asyncio.sleep(1)
            # Select "Anyone with the link" from dropdown/options
            await page.evaluate("""() => {
                const options = document.querySelectorAll(
                    '[role="option"], [role="menuitem"], [role="menuitemradio"], li, label'
                );
                for (const opt of options) {
                    const txt = (opt.innerText || opt.textContent || '').toLowerCase();
                    if (txt.includes('anyone with the link') || txt.includes('anyone')) {
                        opt.click();
                        return 'selected';
                    }
                }
                return '';
            }""")
            await asyncio.sleep(1)
            log(f"[{label}] Set Notebook access to 'Anyone with the link'")

        # Step 2: Get the shareable link
        link = await page.evaluate("""() => {
            // Check input fields for the URL
            const inputs = document.querySelectorAll('input[readonly], input[value*="notebooklm"]');
            for (const inp of inputs) {
                const val = inp.value || '';
                if (val.includes('notebooklm.google.com')) return val;
            }
            // Try clicking "Copy link" button
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const txt = (b.innerText || '').toLowerCase();
                if (txt.includes('copy link') || (txt.includes('copy') && !txt.includes('copy all'))) {
                    b.click();
                    return 'clipboard';
                }
            }
            return '';
        }""")
        if link == 'clipboard':
            await asyncio.sleep(0.5)
            clip = get_clipboard()
            if clip and "notebooklm.google.com" in clip:
                url = clip
        elif link and "notebooklm.google.com" in link:
            url = link

        # Step 3a: DOM-verify the access dropdown reads "Anyone with the
        # link" BEFORE we save. We require a STRICT signal — either:
        #   (a) the dropdown trigger's *own text node* (not its descendants)
        #       contains "anyone with the link", OR
        #   (b) an aria-selected/aria-checked element inside the dialog
        #       contains "anyone with the link".
        # Why so strict: Material-style dropdowns place the option list as a
        # child of the trigger when open; reading `.innerText` on the trigger
        # captures sibling option labels and would falsely match. Reading the
        # trigger's directly-owned text only (childNodes Text nodes) avoids
        # this. The body-only "soft accept" path was removed — too prone to
        # false positives when the dropdown is left open. Better to undercount
        # public-verifies (fall through to URL-shape recovery in the caller)
        # than to falsely confirm a private link.
        try:
            public_verified = bool(await page.evaluate("""() => {
                const PHRASE = 'anyone with the link';
                // Read only the directly-owned text of an element (no descendants).
                const ownText = (el) => {
                    let s = '';
                    for (const n of el.childNodes) {
                        if (n.nodeType === 3 /* TEXT_NODE */) s += n.nodeValue || '';
                    }
                    return s.toLowerCase();
                };
                // Layer (a): dropdown trigger's own text node only.
                const triggers = document.querySelectorAll(
                    '[role="dialog"] [role="combobox"], [role="dialog"] [aria-haspopup="listbox"], ' +
                    '[role="dialog"] button[aria-expanded]'
                );
                for (const t of triggers) {
                    if (ownText(t).includes(PHRASE)) return true;
                }
                // Layer (b): explicit aria-selected/aria-checked element in the dialog.
                const dlg = document.querySelector('[role="dialog"]');
                if (dlg) {
                    const active = dlg.querySelector(
                        '[aria-selected="true"], [aria-checked="true"], [data-selected="true"]'
                    );
                    if (active && (active.innerText || '').toLowerCase().includes(PHRASE)) {
                        return true;
                    }
                }
                return false;
            }"""))
        except Exception as _ve:
            log(f"[{label}] public-access DOM verify skipped: {_ve}", "DEBUG")

        # Step 3b: Click Save/Done to apply the sharing change.
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const txt = (b.innerText || '').trim().toLowerCase();
                if (txt === 'save' || txt === 'done' || txt === 'apply') {
                    b.click();
                    return 'saved';
                }
            }
            return '';
        }""")
        await asyncio.sleep(1)
        if public_verified:
            log(f"[{label}] Public share DOM-verified — link is shareable")
        else:
            log(f"[{label}] Public share NOT DOM-verified — returned link may be private", "WARN")
    except Exception as e:
        log(f"[{label}] NLM public share flow: {e}", "WARN")
    return url, public_verified


async def _ensure_gdoc_public(page) -> bool:
    """Open the Google Doc share dialog and set General access to
    'Anyone with the link' (Editor). DOM-first; returns True on success.
    Designed to be idempotent — safe to call even if already public."""
    try:
        # Click Share button (top-right)
        share_clicked = await page.evaluate("""() => {
            const selectors = [
                'div[aria-label*="Share"][role="button"]',
                'button[aria-label*="Share"]',
                'div[data-tooltip*="Share"]',
                'div[role="button"][aria-label*="Share"]',
            ];
            for (const s of selectors) {
                const el = document.querySelector(s);
                if (el && el.offsetParent !== null) { el.click(); return true; }
            }
            return false;
        }""")
        if not share_clicked:
            return False
        await asyncio.sleep(2)
        # Change "General access" → "Anyone with the link"
        await page.evaluate("""() => {
            const buttons = document.querySelectorAll('button, [role="combobox"], [role="button"]');
            for (const b of buttons) {
                const txt = (b.innerText || b.textContent || '').toLowerCase();
                if (txt.includes('restricted') ||
                    (txt.includes('only') && txt.includes('access'))) {
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
        await asyncio.sleep(1)
        await page.evaluate("""() => {
            const options = document.querySelectorAll('[role="menuitem"], [role="option"], li, span, div');
            for (const opt of options) {
                const txt = (opt.innerText || opt.textContent || '').trim().toLowerCase();
                if (txt === 'anyone with the link' || txt.startsWith('anyone with the link')) {
                    opt.click();
                    return true;
                }
            }
            return false;
        }""")
        await asyncio.sleep(1)
        # Ensure role = Editor (not Viewer/Commenter)
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button, [role="combobox"]');
            for (const b of btns) {
                const txt = (b.innerText || b.textContent || '').toLowerCase();
                if (txt.includes('viewer') || txt.includes('commenter')) {
                    b.click();
                    return;
                }
            }
        }""")
        await asyncio.sleep(0.6)
        await page.evaluate("""() => {
            const opts = document.querySelectorAll('[role="menuitem"], [role="option"], li');
            for (const o of opts) {
                const txt = (o.innerText || o.textContent || '').trim().toLowerCase();
                if (txt === 'editor' || txt.startsWith('editor')) { o.click(); return; }
            }
        }""")
        await asyncio.sleep(0.6)
        # Click Done/Copy link
        await page.evaluate("""() => {
            const btns = document.querySelectorAll('button, [role="button"]');
            for (const b of btns) {
                const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                if (txt === 'done' || txt === 'save' || txt === 'copy link') {
                    b.click();
                    return;
                }
            }
        }""")
        await asyncio.sleep(1)
        return True
    except Exception as e:
        log(f"[gdoc] public-share DOM flow error: {e}", "WARN")
        return False


async def extract_notebooklm_url(browser, cua_client=None, verbose=False, **_):
    """Extract NotebookLM notebook URL after ensuring public sharing is enabled.
    Flow: Share → Notebook access → public → get link → Save.

    `verified=True` requires BOTH a NotebookLM URL shape AND DOM-confirmed
    public-share (Anyone with the link). Without DOM verification, the URL
    could be a private notebook link, which would 404 or "Request access"
    for anyone but the owner downstream in Phase 5's email/Doc.
    """
    page = browser.page
    url = await browser.current_url() or ""
    public_verified = False
    try:
        # Click Share button to open dialog
        share_btn = await page.query_selector(
            'button[aria-label*="Share"], button[aria-label*="share"], '
            '[class*="share"] button'
        )
        if share_btn:
            await share_btn.click()
            await asyncio.sleep(2)
            link, dom_verified = await _set_nlm_public_and_get_link(page, "NotebookLM")
            if link:
                url = link
            public_verified = bool(dom_verified)
            # Close dialog
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.5)
        # CUA fallback if DOM didn't work
        if not url or "notebooklm.google.com/notebook" not in url:
            if cua_client:
                result = await agent_loop(cua_client, browser,
                    "Share this NotebookLM notebook publicly.",
                    "Click the Share button. In the share dialog, change 'Notebook access' to "
                    "'Anyone with the link'. Then click 'Copy link' to get the URL. Click Save. "
                    "Tell me the EXACT URL.",
                    model=CUA_MODEL, max_iterations=10, verbose=verbose)
                m = re.search(r'https://notebooklm\.google\.com/notebook/[^\s]+', (result.get("text") or ""))
                if m:
                    url = m.group(0)
                else:
                    clip = get_clipboard()
                    if clip and "notebooklm.google.com" in clip:
                        url = clip
                # CUA path doesn't expose the share-state DOM, so we can't
                # DOM-verify. Treat as unverified — the run still emits the
                # link, but downstream consumers know it might be private.
    except Exception as e:
        log(f"[NotebookLM] Share dialog failed: {e}", "WARN")
    # Fallback to current tab URL
    if not url or "notebooklm.google.com/notebook" not in url:
        url = await browser.current_url() or ""
    # verified = NotebookLM URL shape + DOM-confirmed public access. URL
    # alone is not sufficient since private/public share the same shape.
    verified = ("notebooklm.google.com/notebook" in url) and public_verified
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


# ── B1: Link-first phase_complete — retry helpers ────────────────────────────

async def extract_with_retry(
    phase: int,
    agent: str,
    browser,
    cua_client,
    extractor_fn,
    max_retries: int = 3,
    retry_delay: float = 3.0,
    **kwargs,
) -> "LinkResult":
    """Run a link extractor up to `max_retries` times, validating each URL.
    Emits link_extracting / link_extract_retry / link_extracted / link_extraction_failed.
    Returns LinkResult with verified=True on success; otherwise verified=False + error."""
    last_err = ""
    for attempt in range(1, max_retries + 1):
        emit_event("link_extracting", phase=phase, agent=agent,
                   attempt=attempt, maxAttempts=max_retries)
        log(f"[{agent}] Link extract attempt {attempt}/{max_retries}")
        try:
            result = await extractor_fn(browser, cua_client=cua_client, **kwargs)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            result = LinkResult(url="", label=kwargs.get("label", ""),
                                platform=agent, verified=False, error=last_err)
        # Validate URL against _LINK_VALIDATORS + _BAD_URL_PATTERNS
        if result.success and validate_link(agent, result.url):
            result.verified = True
            label = result.label or kwargs.get("label", f"{agent} link")
            emit_event("link_extracted", phase=phase, agent=agent,
                       url=result.url, label=label, verified=True, attempt=attempt)
            log(f"[{agent}] Link VERIFIED on attempt {attempt}: {result.url}")
            return result
        # Failed this attempt — log and retry
        last_err = result.error or (
            f"URL failed validation: {result.url[:80]}" if result.url else "No URL returned"
        )
        log(f"[{agent}] Attempt {attempt}/{max_retries} failed: {last_err}", "WARN")
        if attempt < max_retries:
            emit_event("link_extract_retry", phase=phase, agent=agent,
                       attempt=attempt, maxAttempts=max_retries, error=last_err)
            await asyncio.sleep(retry_delay)
    # All retries exhausted. Include a human-readable description so the
    # frontend step list shows something meaningful ("Couldn't extract link
    # after N attempts") instead of the raw event name, and so the agent
    # alert panel has content to render if a caller routes this as a
    # terminal failure rather than proceeding to wait_for_agent_decision.
    emit_event("link_extraction_failed", phase=phase, agent=agent,
               error=last_err, attempts=max_retries,
               description=f"Couldn't extract a verified link after {max_retries} attempts")
    return LinkResult(url="", label=kwargs.get("label", ""),
                      platform=agent, verified=False, error=last_err)


async def wait_for_agent_decision(agent: str, reason: str, phase: int = 2,
                                   options=("retry", "skip")) -> str:
    """Emit agent_link_failed, pause pipeline, wait for user's decision.
    Returns 'retry' | 'skip' — and may return 'stop' if the user hit Stop
    from the chat input bar while the banner was up (caught via
    _controls.is_stop()). The banner itself no longer offers Stop as a
    button; pipeline-level stop lives in the chat bar only (2026-04-19
    design rule applied to AgentAlertPanel)."""
    _controls.pending_agent_decision = None
    emit_event("agent_link_failed", phase=phase, agent=agent,
               reason=reason, options=list(options))
    _controls.request_pause()
    emit_event("pipeline_paused", phase=phase, reason="agent_link_failed", agent=agent)
    log(f"[{agent}] Waiting for user decision (retry/skip) — reason: {reason}")
    await _controls.wait_if_paused()
    if _controls.is_stop():
        return "stop"
    decision = _controls.pop_agent_decision() or "skip"
    emit_event("pipeline_resumed", phase=phase, reason=f"agent_decision:{decision}", agent=agent)
    log(f"[{agent}] User decision: {decision}")
    return decision


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

    platform_key = (platform or "").strip().lower()
    for attempt in range(1, max_retries + 1):
        pasted = False
        # Narrate each outer-loop attempt to the frontend. Per-strategy emits
        # would be too noisy (4 strategies × 3 attempts = 12 events per paste),
        # so we emit once per outer attempt with a "retrying" badge. First
        # attempt is silent; retries appear as "X: paste retry N/M…".
        if attempt > 1:
            try:
                emit_event("pipeline_warning", phase=2, agent=platform_key or None,
                           message=f"{label}: paste retry {attempt}/{max_retries}…",
                           details=f"Previous paste attempt didn't land the brief in the composer. Retrying with a fresh strategy cycle.",
                           alertType="retrying")
            except Exception:
                pass
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

                # Strategy 3: Playwright keyboard.insert_text (no clipboard needed,
                # but sends everything as one big inserted blob — some composers
                # like Gemini's rich-textarea don't always update controller state
                # on a single insert event).
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

                # Strategy 4: Real keyboard type — dispatches a genuine keydown/
                # keypress/keyup per character, which any controlled composer
                # has to handle (that's the contract of a browser). Slower
                # (~0.5–2s for typical briefs) but virtually always works, and
                # it's the only thing that reliably gets past Gemini's
                # rich-textarea when CDP paste / execCommand / insert_text all
                # leave the composer visually empty.
                if not pasted:
                    try:
                        await ta.click()
                        await page.keyboard.press("Control+a")
                        await asyncio.sleep(0.1)
                        await page.keyboard.press("Delete")
                        await asyncio.sleep(0.1)
                        # delay=2ms per char keeps it realistic without adding
                        # seconds to the run (a 5k-char brief is ~10s of typing).
                        await page.keyboard.type(brief_text, delay=2)
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
        # For Gemini, `div[contenteditable="true"]` can match a non-composer
        # sidebar element; also try the explicit rich-textarea path so we
        # don't falsely fail a successful paste just because we read the
        # wrong container.
        try:
            content_len = await page.evaluate("""() => {
                const candidates = [
                    '#prompt-textarea',
                    'rich-textarea div[contenteditable="true"]',
                    '.ProseMirror',
                    'div[contenteditable="true"][data-placeholder]',
                    'div[contenteditable="true"]',
                    'textarea[placeholder]',
                    'textarea',
                ];
                let best = 0;
                for (const sel of candidates) {
                    for (const el of document.querySelectorAll(sel)) {
                        if (el.offsetParent === null) continue;  // must be visible
                        const txt = (el.innerText || el.value || el.textContent || '');
                        if (txt.length > best) best = txt.length;
                    }
                }
                return best;
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

# T2 narrator ring buffer. Populated by emit_event, read by _narrator_loop.
# Bounded at 50 — wide enough to cover ~2-5 min at typical event density,
# tight enough that the narrator prompt never balloons. Appended AFTER the
# Firestore write so the frontend and the ring-buffer never diverge in
# order. Do NOT rely on this for frontend-observable state — it's a
# backend-only snapshot for narration prompts.
_recent_events: "collections.deque" = collections.deque(maxlen=50)


def _recent_events_window(seconds: float) -> list:
    """Return recent events no older than `seconds`, oldest → newest.
    Filters out `phase_narration` so the narrator doesn't feed on its
    own output (would produce drift + hall-of-mirrors summaries)."""
    cutoff_ms = int((time.time() - seconds) * 1000)
    out = []
    for e in list(_recent_events):
        if e.get("timestamp", 0) < cutoff_ms:
            continue
        if e.get("type") == "phase_narration":
            continue
        out.append(e)
    return out


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
    # Drop into the narrator ring buffer (after Firestore so ordering
    # cannot drift between what the frontend sees and what the narrator
    # reasons from).
    try:
        _recent_events.append(event)
    except Exception:
        pass
    # B3: keep _runtime.phase in sync with the actual running phase so that
    # rate-limit warnings (and any other `phase` fallback inside agent_loop)
    # land on the correct phase badge instead of drifting to a stale one.
    # Must happen BEFORE narrator start so narrators for a new phase see
    # the updated value. Agnostic of caller — every phase_start site gets
    # the runtime invariant for free.
    if event_type == "phase_start" and isinstance(phase, int) and phase >= 0:
        try:
            _runtime.phase = phase
        except Exception:
            pass
    # T2 narrator lifecycle — auto-wired to phase boundaries so every
    # phase_start / phase_complete / phase_skipped / pipeline_stopped site
    # doesn't need manual start/stop_narrator calls. Single point of truth.
    try:
        if event_type == "phase_start" and isinstance(phase, int) and phase >= 0:
            start_narrator(phase)
        elif event_type in ("phase_complete", "phase_skipped",
                             "pipeline_stopped", "pipeline_complete"):
            stop_narrator()
    except Exception:
        pass


def start_narration_ticker(phase, agent, narration, interval=30, expected_minutes=None):
    """Spawn a background task that emits agent_progress every `interval`s
    with `narration` + elapsed time. Returns the (stop_event, task) pair —
    caller must call stop_event.set() and await task to clean up.

    Used to keep P3/P4/P5 dropdowns alive during long CUA agent_loop calls
    so the narration matches P2's ~30s round-robin cadence. Without this,
    long CUA waypoints leave the FE sitting on a stale pre-call string.

    Usage:
        stop, task = start_narration_ticker(4, "youtube",
                                            "Uploading video to YouTube Studio")
        try:
            await agent_loop(...)
        finally:
            stop.set()
            await task
    """
    stop = asyncio.Event()

    async def _tick():
        elapsed = 0
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                elapsed += interval
                try:
                    mm, ss = divmod(elapsed, 60)
                    label = (f"{narration}… ({mm}m {ss}s elapsed)" if mm
                             else f"{narration}… ({ss}s elapsed)")
                    kw = {"phase": phase, "agent": agent,
                          "status": "working", "progress": label,
                          "elapsedSec": elapsed}
                    if expected_minutes:
                        kw["expectedMinutes"] = expected_minutes
                    emit_event("agent_progress", **kw)
                except Exception:
                    pass

    task = asyncio.create_task(_tick())
    return stop, task


async def stop_narration_ticker(stop, task):
    """Companion to start_narration_ticker — sets the stop event and awaits
    the ticker task. Safe to call when stop/task are None (no-op)."""
    if stop is None or task is None:
        return
    try:
        stop.set()
    except Exception:
        pass
    try:
        await task
    except Exception:
        pass


async def _shadow_observed_cua(
    page, *, hotspot_id, phase, platform, current_step,
    context_hint, cua_coro_factory, expected_outcome="",
):
    """Run a CUA call, optionally shadowed by Vision (DG_VISION_TIER=shadow).

    Default behavior (flag off / module unavailable): just runs CUA. Shadow
    mode: Vision runs in PARALLEL with CUA via asyncio.gather, logs Vision's
    proposed action to logs/vision_shadow.jsonl, but CUA's output is what's
    returned. Vision NEVER touches the page — zero pipeline risk.

    cua_coro_factory: a no-arg async function returning the CUA result.
    Defining it as a closure at the call site lets us reuse the existing
    asyncio.wait_for + agent_loop wrapping per-site.

    Failure modes (Vision side) are silently logged — never re-raised.
    Hotspot ids match scratch/vision_hotspots.md (#7c, #7c-p1, #7d, #2c, #2d).
    """
    if _vision is None:
        return await cua_coro_factory()
    try:
        if _vision.is_vision_enabled() != "shadow":
            return await cua_coro_factory()
    except Exception:
        return await cua_coro_factory()

    flow_ctx = {
        "workflow_name": hotspot_id,
        "phase": phase,
        "platform": platform,
        "current_step": current_step,
        "expected_outcome": expected_outcome,
        "context_hint": context_hint,
        "attempts": 1,
    }
    try:
        return await _vision.shadow_observe_then_cua(
            page, cua_coro_factory,
            flow_context=flow_ctx,
            hotspot_id=hotspot_id,
            run_id=os.environ.get("DG_RUN_ID"),
        )
    except Exception as _se:
        log(f"[shadow:{hotspot_id}] shadow path failed, falling back to direct CUA: {_se}",
            "WARN")
        return await cua_coro_factory()


def fail_phase(phase, error, reason=None, agent=None, actions=None, **extra):
    """Soft-pause a phase on an unrecoverable error. Emits pipeline_error
    ONLY — never pipeline_stopped, never Firestore status=failed. The
    pipeline sits alive awaiting the user's decision, which the caller
    picks up with `await _controls.await_phase_decision(phase)`.

    ARCHITECTURE CHANGE 2026-04-18 (never-die contract): Previously this
    helper also emitted pipeline_stopped + marked the run as failed, which
    tore the pipeline down as soon as a phase hit an issue. New contract:
    the pipeline only terminates on an explicit user Stop click. Every
    other failure surfaces as a phase alert with Retry/Skip/Stop buttons
    and waits for the user.

    Every event carries phase + (optional) agent so the frontend can route
    to the right alert panel without guessing. `reason` is human copy shown
    in the alert details; `error` stays as a short machine-tag. `actions`
    defaults to ['retry','skip'] — callers can override when a retry path
    isn't meaningful (rare)."""
    payload = {"error": error}
    if reason:
        payload["reason"] = reason
    # PhaseAlertPanel expects action objects, not bare ids. Default to
    # [Retry, Skip] tied to the retry_phase / skip_phase command listener.
    # Callers can override with their own shape when specific semantics
    # are required (e.g. resume_from_checkpoint).
    payload["actions"] = actions if actions else [
        {"id": "retry", "label": "Retry", "style": "primary",
         "command": {"action": "retry_phase", "phase": phase}},
        {"id": "skip", "label": "Skip", "style": "default",
         "command": {"action": "skip_phase", "phase": phase}},
    ]
    payload.update(extra)
    emit_event("pipeline_error", phase=phase, agent=agent, **payload)


# ── T2: Phase narration (Gemini Flash — one human sentence per tick) ─────────
# A per-phase async task that watches the ring buffer and emits a
# `phase_narration` event every few seconds so the user always sees a live
# story in the phase dropdown, not just raw progress bars. Tight (6s) during
# data-rich phases (P1 brief, P2 parallel DR) so the narration can cite real
# scrape content; looser (20s) during scripted phases (P0/3/4/5) where state
# changes in chunky steps. Cost ~$0.02/run on Gemini 2.0 Flash.
#
# Interaction with T4 watchdog: each `phase_narration` emit flows through
# the frontend's `markEventReceived` → refreshes `eventSilenceSec`, so the
# watchdog stays in "alive" state during genuine work. When the backend
# really dies, narration stops too — and watchdog correctly flips to silent.

PHASE_FLOW_CONTEXT = {
    0: ("Phase 0 is the warmup: launch a dedicated Chrome profile and probe "
        "that ChatGPT, Gemini, Claude, NotebookLM, YouTube, Gmail, and "
        "Google Docs are all logged in. With skipInitVerify the probe is a "
        "cookie sniff (<10s); full verify is a per-platform CUA round (1-2 min)."),
    1: ("Phase 1 is brief generation. ChatGPT Pro with Extended Thinking "
        "drafts a detailed research brief from the topic + any PDFs. The "
        "flow is: open ChatGPT, clear any HV gate, select Pro + Thinking, "
        "attach PDFs, submit the brief prompt, then ~10-20 min of reasoning "
        "+ writing while the frontend token-streams the output."),
    2: ("Phase 2 is parallel deep research. ChatGPT Deep Research, Gemini "
        "Deep Research, and Claude Adaptive Thinking + Research tools run "
        "at the same time with the same brief. Each crawls 40-60+ sources "
        "and produces an independent 5-15k-word markdown report. Runs "
        "30-90 min; per-agent sources, sections, and thinking stream live."),
    3: ("Phase 3 is NotebookLM: upload each agent's .md to Google "
        "NotebookLM, rename the notebook, make it public, then generate a "
        "podcast-style audio overview where two AI hosts discuss the "
        "findings. Upload + audio gen together take 15-25 min."),
    4: ("Phase 4 is video: render a thumbnail, wrap the audio + thumbnail "
        "into an MP4 with ffmpeg, then upload the video to YouTube as "
        "unlisted. Processing + URL extraction together take 3-8 min."),
    5: ("Phase 5 is delivery: create a Google Doc hub listing every output "
        "link (brief, reports, NotebookLM, YouTube), make it publicly "
        "shareable, and email the user a notification with every link via "
        "Gmail."),
}

_narrator_task = None  # type: asyncio.Task | None


def _narrator_cadence_for_phase(phase: int) -> float:
    # P1+P2 stream rich real data — tighter cadence catches sub-step changes.
    # P0/3/4/5 transition in chunky deterministic steps — 20s is plenty.
    return 6.0 if phase in (1, 2) else 20.0


def _compact_event_for_narration(e: dict) -> str:
    """Flatten an event into one line for the narrator prompt. Skips
    high-cardinality fields and caps each value at 120 chars so a 20-event
    window stays well under the Gemini Flash input budget."""
    t = e.get("type", "")
    ph = e.get("phase", "")
    ag = e.get("agent", "")
    d = e.get("data", {}) or {}
    parts = [f"{t} ph={ph}"]
    if ag:
        parts.append(f"agent={ag}")
    for k in ("status", "progress", "error", "message", "reason",
              "sources", "sections", "partialTextLen", "elapsedSec"):
        v = d.get(k)
        if v in (None, "", [], {}):
            continue
        if isinstance(v, (list, dict)):
            s = json.dumps(v)[:120]
        else:
            s = str(v)[:120]
        parts.append(f"{k}={s}")
    return " | ".join(parts)


async def _narrator_loop(phase: int):
    """Poll the ring buffer every `cadence` seconds. Synthesize one human
    sentence (phase-wide) plus, for Phase 2, one sentence per active agent.
    Emits `phase_narration` always and `agent_narration` for Phase 2.
    Back off on 429 / network blip."""
    if not GEMINI_API_KEY:
        return
    if phase is None or phase < 0:
        return
    cadence = _narrator_cadence_for_phase(phase)
    last_narration = ""
    last_agent_lines: dict[str, str] = {}
    backoff_ticks_left = 0
    try:
        import requests as _requests
    except Exception:
        return
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    )

    def _call_gemini(system: str, user_msg: str, max_tokens: int = 80):
        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
        }
        try:
            resp = _requests.post(url, json=payload, timeout=5)
        except Exception:
            return None, 0
        try:
            j = resp.json()
            text = (j.get("candidates", [{}])[0]
                     .get("content", {})
                     .get("parts", [{}])[0]
                     .get("text", ""))
        except Exception:
            return None, resp.status_code
        return (text or "").strip(), resp.status_code

    try:
        while True:
            await asyncio.sleep(cadence if backoff_ticks_left == 0 else 15.0)
            if backoff_ticks_left > 0:
                backoff_ticks_left -= 1
            try:
                if _controls.is_stop() or _controls.is_pause():
                    continue
            except Exception:
                pass
            recent = _recent_events_window(30.0)
            phase_ctx = PHASE_FLOW_CONTEXT.get(phase, "")
            data_rich = phase in (1, 2)
            style_note = (
                "CITE the real scrape content when you can — reference specific "
                "source counts, section titles, or partialTextLen numbers you see "
                "in the events. Do not invent specifics."
                if data_rich else
                "Reason from the hardcoded phase flow + elapsed time + last status "
                "transition. Do not invent specific numbers."
            )
            system = (
                "You narrate ONE human sentence summarizing what the Super Research "
                "pipeline is doing RIGHT NOW for a user watching the phase dropdown. "
                f"Phase {phase}: {phase_ctx} {style_note} "
                "Output exactly ONE sentence, <= 110 chars. No markdown. No prefix "
                "like 'Currently' or 'Status:'. No em-dashes. If the events show "
                "nothing new, say something like 'Still working on <last known step>.'"
            )
            event_lines = "\n".join(
                f"- {_compact_event_for_narration(e)}" for e in recent[-20:]
            )
            user_msg = f"Recent events (newest last):\n{event_lines or '[none]'}"

            text, status_code = await asyncio.to_thread(_call_gemini, system, user_msg)
            if status_code == 429:
                backoff_ticks_left = 3
                continue
            if not text or status_code >= 400:
                continue
            text = text.strip().strip('"').strip("`").strip()
            if text and text != last_narration:
                last_narration = text
                try:
                    emit_event("phase_narration", phase=phase, text=text)
                except Exception:
                    pass

            # ── Phase 2: per-agent narration ──
            # Filter the recent window per agent and emit one
            # `agent_narration` per active agent so the accordion row
            # carries live context scoped to that platform.
            if phase == 2:
                agent_keys = ("chatgpt", "gemini", "claude")
                for akey in agent_keys:
                    a_events = [e for e in recent
                                if (e.get("agent") or "").lower() == akey
                                or (e.get("data", {}) or {}).get("agent", "").lower() == akey]
                    if not a_events:
                        continue
                    a_lines = "\n".join(
                        f"- {_compact_event_for_narration(e)}" for e in a_events[-12:]
                    )
                    a_system = (
                        f"You narrate ONE human sentence about what the {akey.upper()} "
                        "agent is doing RIGHT NOW in the Super Research Phase 2 (deep "
                        "research) run. CITE the real numbers (sources, chars, sections) "
                        "when they appear in the events. Output exactly ONE sentence, "
                        "<= 100 chars. No markdown. No prefix. No em-dashes."
                    )
                    a_user = (
                        f"Recent events for {akey.upper()} (newest last):\n"
                        f"{a_lines or '[none]'}"
                    )
                    a_text, a_status = await asyncio.to_thread(_call_gemini, a_system, a_user, 60)
                    if a_status == 429:
                        backoff_ticks_left = 3
                        break
                    if not a_text or a_status >= 400:
                        continue
                    a_text = a_text.strip().strip('"').strip("`").strip()
                    if a_text and a_text != last_agent_lines.get(akey):
                        last_agent_lines[akey] = a_text
                        try:
                            emit_event("agent_narration", phase=2,
                                       agent=akey, text=a_text)
                        except Exception:
                            pass
    except asyncio.CancelledError:
        return
    except Exception as _e:
        try:
            log(f"[narrator] loop crashed ({_e}) — narration stopped for phase {phase}", "WARN")
        except Exception:
            pass
        return


def start_narrator(phase: int):
    """Cancel any existing narrator task and start a fresh one scoped to
    this phase. Wired automatically from emit_event on `phase_start`.
    Safe to call when there's no running event loop (silently no-ops)."""
    global _narrator_task
    try:
        if _narrator_task and not _narrator_task.done():
            _narrator_task.cancel()
    except Exception:
        pass
    try:
        _narrator_task = asyncio.create_task(_narrator_loop(phase))
    except RuntimeError:
        # No running event loop (pre-startup / CLI paths). Skip.
        _narrator_task = None


def stop_narrator():
    """Cancel the narrator task. Wired automatically from emit_event on
    `phase_complete` / `phase_skipped`. Also called explicitly by
    orchestrator teardown / exception paths."""
    global _narrator_task
    try:
        if _narrator_task and not _narrator_task.done():
            _narrator_task.cancel()
    except Exception:
        pass
    _narrator_task = None


# ── Login URL negatives (shared between Phase 0 preflight + setup) ─────
# Known login-wall host fragments. When the browser lands on one of
# these after a navigation, the profile is not authenticated on that
# platform. Cheap short-circuit before spending CUA.

_LOGIN_HOST_NEGATIVES = (
    "auth.openai.com", "accounts.google.com/signin",
    "login.live.com", "claude.ai/login", "claude.ai/signup",
)

# NOTE (2026-04-24): `await_phase_login_probe` used to live here as a
# per-phase cookie-only gate called at the start of Phases 1-5. It
# turned every transient cookie blip into a mid-run `login_required`
# banner even when Phase 0 had just verified successfully. The layer
# is deleted — Phase 0 is now the single source of truth for login
# state. If a session really drifts mid-run, the phase's own driving
# code (ChatGPT navigation, NotebookLM upload, etc.) will surface a
# concrete failure through fail_phase with a specific reason, which
# the existing PhaseAlertPanel handles without the generic
# "Login required" noise.


async def scrape_progress_chatgpt(page):
    """Scrape ChatGPT's current research progress (Playwright JS — zero CUA cost).
    Returns rich data for web app: status, thinking steps, sources, sections, text length.

    Deep Research note: as of 2026, ChatGPT Deep Research renders inside a cross-origin
    iframe (connector_openai_deep_research.web-sandbox.oaiusercontent.com). Main-page
    selectors miss DR content, so we iterate `page.frames` and scrape the DR frame
    separately, then merge. Main-page signals (title, model, stop button) still come
    from the host page."""
    try:
        # ---- Main-page scrape (host page: title, model, stop button, chat-level DR indicators)
        result = await page.evaluate("""() => {
            const r = {
                status: 'unknown', phase: '', progress: '', thinking: '',
                sources: 0, source_urls: [], sections: [], steps: [],
                partial_text_len: 0, plan: '', model: '', title: '',
                dr_active: false, dr_done_text: false, has_stop_btn: false
            };
            // Model info
            const modelEl = document.querySelector('[data-testid="model-selector"], .model-label');
            if (modelEl) r.model = modelEl.innerText.substring(0, 50);
            // Conversation title
            const titleEl = document.querySelector('h1, [data-testid="conversation-title"]');
            if (titleEl) r.title = titleEl.innerText.substring(0, 100);
            // Stop-button detection (aria-label + text fallback)
            r.has_stop_btn = !!document.querySelector(
                'button[aria-label="Stop generating"], button[aria-label*="Stop"], ' +
                'button[data-testid="stop-button"], button[data-testid*="stop"]'
            );
            if (!r.has_stop_btn) {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    const t = (b.textContent || '').trim().toLowerCase();
                    if (t === 'stop' || t === 'stop generating' || t === 'stop research') { r.has_stop_btn = true; break; }
                }
            }
            // Body-level DR indicators (host page shows banner/status strings even when content is in iframe)
            const bodyLower = document.body.innerText.toLowerCase();
            const drKws = ['researching', 'sources found', 'sources and counting',
                          'searching the web', 'reading sources', 'analyzing',
                          'deep research', 'looking into', 'investigating'];
            r.dr_active = drKws.some(kw => bodyLower.includes(kw));

            // 2026-04-26 v3: extract the COLLAPSED activity strip BEFORE the
            // side panel opens. Strip wording: "Looking into Hermes memory
            // system... 196 searches". Without this, FE per-platform card
            // shows empty narration for the first 3 min (gate is 180s).
            // Verb regex constrained to start-of-string + count badge so
            // stale chat text (user prompts, prior responses) won't match.
            try {
                const VERB = /^(checking|searching|looking|browsing|investigating|analyzing|reading|exploring)\\b/i;
                const COUNT = /\\b\\d+\\s+(?:searches?|sources?|results?)\\b/i;
                let stripText = '';
                let stripTop = -1;
                const cands = document.querySelectorAll('div, button, [role="button"], li');
                for (const el of cands) {
                    const t = (el.innerText || '').trim();
                    if (!t || t.length < 6 || t.length > 220) continue;
                    if (!(VERB.test(t) && COUNT.test(t))) continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    if (rect.top > stripTop) { stripText = t.slice(0, 200); stripTop = rect.top; }
                }
                if (stripText) {
                    r.progress = stripText;
                    r.steps.push(stripText);
                }
            } catch(e) {}
            // Completion indicators
            const doneKws = ['research completed', 'research complete',
                             'finished research', 'deep research completed'];
            r.dr_done_text = doneKws.some(kw => bodyLower.includes(kw));
            // Thinking/research progress (host page, rare in iframe DR but kept for chat mode)
            const thinking = document.querySelector('.thinking-text, [data-thinking], .research-progress, .step-text');
            if (thinking) r.thinking = thinking.innerText.substring(0, 500);
            // Sources/citations (host page — kept for non-DR chat)
            const srcSet = new Set();
            document.querySelectorAll(
                '.citation, .source-link, [data-citation], ' +
                '[data-message-author-role="assistant"] a[href*="http"], ' +
                '[data-testid="canvas"] a[href*="http"], .canvas-container a[href*="http"]'
            ).forEach(s => {
                const href = s.href || '';
                if (href.startsWith('http') && !href.includes('chatgpt.com') && !href.includes('openai.com') && !href.includes('chat.openai') && !href.includes('oaiusercontent') && href.length < 500)
                    srcSet.add(href);
            });
            r.source_urls = Array.from(srcSet).slice(0, 30);
            r.sources = r.source_urls.length;
            // Response sections (host page headings)
            const headings = document.querySelectorAll('[data-message-author-role="assistant"] h1, [data-message-author-role="assistant"] h2, [data-message-author-role="assistant"] h3');
            r.sections = Array.from(headings).map(h => h.innerText.substring(0, 80));
            // Partial response length (host page)
            const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
            if (msgs.length > 0) r.partial_text_len = msgs[msgs.length-1].innerText.length;
            // Canvas/artifact content
            const canvas = document.querySelector('[data-testid="canvas"], .canvas-container, .canvas-content');
            if (canvas && canvas.innerText.length > r.partial_text_len) r.partial_text_len = canvas.innerText.length;
            return r;
        }""")

        # ---- Host-page side-panel scrape (P1 Pro+ET, also catches P2 host-side panel)
        # P1 mode renders the activity panel inline on the host page (no DR
        # sandbox iframe). After _open_chatgpt_activity_panel clicks the strip,
        # the side panel mounts as <aside>/[role=complementary]/panel-class div
        # on the right ~30-40% of viewport. The iframe block below only matches
        # P2 DR; this block fills the P1 gap with a Gemini-style wide-net sweep
        # of the panel root: VERB-prefixed step rows, generic a[href] sources
        # with chatgpt.com redirector unwrap + chrome filter, h1/h2/h3 sections.
        # Returns panel_found:false when no host-side panel exists (e.g. P2 DR
        # where panel is iframe-rooted) → no-op merge, iframe block runs next.
        try:
            hp = await page.evaluate("""() => {
                const out = { steps: [], source_urls: [], sections: [], progress: '', panel_found: false };
                const sels = [
                    'aside', '[role="complementary"]', '[role="region"]',
                    '[aria-label*="source" i]', '[aria-label*="research" i]',
                    '[aria-label*="activity" i]',
                    '[class*="panel" i][class*="side" i]',
                    '[class*="research" i][class*="panel" i]',
                    '[class*="activity" i][class*="panel" i]'
                ];
                let root = null;
                for (const sel of sels) {
                    for (const el of document.querySelectorAll(sel)) {
                        const rc = el.getBoundingClientRect();
                        if (rc.width < 280 || rc.height < 200) continue;
                        if (rc.right < window.innerWidth * 0.55) continue;
                        const inner = (el.innerText || '').trim();
                        if (inner.length < 50) continue;
                        root = el; break;
                    }
                    if (root) break;
                }
                if (!root) return out;
                out.panel_found = true;
                const VERB = /^(checking|searching|looking|browsing|investigating|analyzing|reading|exploring|visiting|researching|thinking|reasoning)\\b/i;
                const rowEls = Array.from(root.querySelectorAll('div, li, [role="listitem"], button, [role="button"], p'));
                const seenKey = new Set();
                const rows = [];
                for (const el of rowEls) {
                    const t = (el.innerText || '').trim();
                    if (!t || t.length < 4 || t.length > 220) continue;
                    const hasCheck = !!el.querySelector('svg[class*="check"], svg[data-icon*="check"]');
                    const hasSpin  = !!el.querySelector('svg[class*="spin"], svg[class*="loader"], [class*="animate-spin"]');
                    const verbHit  = VERB.test(t);
                    if (!verbHit && !hasCheck && !hasSpin) continue;
                    const key = t.slice(0, 60);
                    if (seenKey.has(key)) continue;
                    seenKey.add(key);
                    rows.push({ t: t.slice(0, 200), hasSpin, hasCheck, verbHit });
                }
                out.steps = rows.map(r => r.t).slice(-15);
                const live = rows.find(r => r.hasSpin) || rows.find(r => r.verbHit && !r.hasCheck);
                if (live) out.progress = live.t.slice(0, 160);
                else if (out.steps.length) out.progress = out.steps[out.steps.length - 1];
                const srcSet = new Set();
                root.querySelectorAll('a[href^="http"]').forEach(a => {
                    let h = a.href || '';
                    if (!h || h.length >= 500) return;
                    try {
                        if (h.includes('chatgpt.com/') && h.includes('url=')) {
                            const u = new URL(h);
                            const real = u.searchParams.get('url');
                            if (real && real.startsWith('http')) h = decodeURIComponent(real);
                        }
                    } catch(e) {}
                    if (h.includes('chatgpt.com') || h.includes('openai.com') ||
                        h.includes('oaiusercontent') || h.includes('chat.openai')) return;
                    srcSet.add(h);
                });
                out.source_urls = Array.from(srcSet).slice(0, 30);
                out.sections = Array.from(root.querySelectorAll('h1, h2, h3'))
                    .map(h => (h.innerText || '').trim().slice(0, 80))
                    .filter(s => s.length > 1);
                return out;
            }""")
            if hp and hp.get("panel_found"):
                if hp.get("source_urls"):
                    seen_h = set(result.get("source_urls") or [])
                    unioned_h = list(result.get("source_urls") or [])
                    for u in hp["source_urls"]:
                        if u not in seen_h:
                            seen_h.add(u); unioned_h.append(u)
                    if len(unioned_h) > result.get("sources", 0):
                        result["source_urls"] = unioned_h[:30]
                        result["sources"] = len(result["source_urls"])
                if hp.get("steps") and len(hp["steps"]) > len(result.get("steps") or []):
                    result["steps"] = hp["steps"]
                if hp.get("progress"):
                    result["progress"] = hp["progress"]
                if hp.get("sections") and len(hp["sections"]) > len(result.get("sections") or []):
                    result["sections"] = hp["sections"]
        except Exception as _hpe:
            log(f"ChatGPT host-panel scrape skipped: {_hpe}", "DEBUG")

        # ---- Iframe scrape (Deep Research content lives here as of 2026)
        try:
            for frame in page.frames:
                try:
                    src = (frame.url or "").lower()
                except Exception:
                    continue
                if not src:
                    continue
                # Match any OpenAI DR sandbox iframe (URL substring varies)
                if ("deep_research" in src or "oaiusercontent" in src or "web-sandbox.oaiusercontent" in src):
                    try:
                        dr = await frame.evaluate("""() => {
                            const d = {
                                steps: [], source_urls: [], sections: [],
                                partial_text_len: 0, progress: '', thinking: '',
                                is_active: false, is_done: false
                            };
                            // 1. Steps: DR shows an activity/timeline panel
                            const stepEls = document.querySelectorAll(
                                '[class*="step"], [class*="activity"], [class*="timeline"] li, ' +
                                '[data-step], [class*="research-step"], ' +
                                'li[class*="activity"], [role="listitem"]'
                            );
                            d.steps = Array.from(stepEls).map(e => (e.innerText || '').trim().substring(0, 180))
                                                         .filter(s => s.length > 3).slice(-12);
                            // 2. Sources: DR shows a source list — collect http links inside iframe
                            const srcSet = new Set();
                            document.querySelectorAll('a[href^="http"]').forEach(a => {
                                const h = a.href || '';
                                if (h.length < 500 &&
                                    !h.includes('chatgpt.com') && !h.includes('openai.com') &&
                                    !h.includes('oaiusercontent')) srcSet.add(h);
                            });
                            d.source_urls = Array.from(srcSet).slice(0, 30);
                            // 3. Headings in the DR report
                            const hs = document.querySelectorAll('h1, h2, h3');
                            d.sections = Array.from(hs).map(h => (h.innerText || '').trim().substring(0, 80))
                                                       .filter(s => s.length > 1);
                            // 4. Partial text — use body text as proxy
                            d.partial_text_len = (document.body?.innerText || '').length;
                            // 5. Activity detection inside iframe
                            const bodyLower = (document.body?.innerText || '').toLowerCase();
                            const activeKws = ['researching', 'searching', 'reading', 'analyzing',
                                               'sources found', 'sources and counting', 'browsing'];
                            d.is_active = activeKws.some(kw => bodyLower.includes(kw));
                            // 6. Completion indicators inside iframe
                            const doneKws = ['research completed', 'finished research',
                                             'deep research completed'];
                            d.is_done = doneKws.some(kw => bodyLower.includes(kw));
                            // 7. Latest step as progress
                            if (d.steps.length > 0) d.progress = d.steps[d.steps.length - 1];
                            return d;
                        }""")
                        if dr:
                            # Merge: iframe data is authoritative for DR content
                            if dr.get("partial_text_len", 0) > result.get("partial_text_len", 0):
                                result["partial_text_len"] = dr["partial_text_len"]
                            iframe_srcs = dr.get("source_urls") or []
                            if len(iframe_srcs) > result.get("sources", 0):
                                result["source_urls"] = iframe_srcs
                                result["sources"] = len(iframe_srcs)
                            if dr.get("steps"):
                                result["steps"] = dr["steps"]
                                if dr.get("progress"):
                                    result["progress"] = dr["progress"]
                            if dr.get("sections"):
                                # prefer iframe sections (the actual DR report)
                                result["sections"] = dr["sections"]
                            # Status override from iframe signals
                            if dr.get("is_active"):
                                result["dr_active"] = True
                            if dr.get("is_done"):
                                result["dr_done_text"] = True
                    except Exception as _ie:
                        log(f"ChatGPT DR iframe evaluate skipped: {_ie}", "DEBUG")
                    # ── Actively expand the "Cited sources" panel ──
                    # ChatGPT DR collapses the sources list by default — the
                    # `<a href>` nodes inside it are NOT rendered until the
                    # user clicks the panel. The default scrape above misses
                    # those links and undercounts sources (often 0–3 instead
                    # of 10–20). On by default — opt out via
                    # DG_SOURCE_PANEL_EXPAND=0/false/no. Wrapped in try/except
                    # so any failure silently keeps the partial result we
                    # already collected.
                    if os.environ.get("DG_SOURCE_PANEL_EXPAND", "1").lower() not in ("0", "false", "no"):
                        try:
                            click_res = await frame.evaluate("""() => {
                                const candidates = document.querySelectorAll('button, [role="button"]');
                                for (const b of candidates) {
                                    const t = (b.textContent || '').trim().toLowerCase();
                                    const al = (b.getAttribute('aria-label') || '').toLowerCase();
                                    const isSourcesLabel =
                                        t === 'sources' || t === 'cited sources' ||
                                        /^\\d+\\s+sources?$/.test(t) ||
                                        al.includes('cited source') || al === 'sources';
                                    if (!isSourcesLabel) continue;
                                    const expanded = b.getAttribute('aria-expanded');
                                    if (expanded === 'true') {
                                        return { clicked: false, alreadyExpanded: true, label: t || al };
                                    }
                                    b.click();
                                    return { clicked: true, label: t || al };
                                }
                                return { clicked: false, found: false };
                            }""")
                            if click_res and click_res.get("clicked"):
                                # Lazy render needs a beat. 1.0s is generous —
                                # the list either appears immediately or the
                                # panel was already populated.
                                await asyncio.sleep(1.0)
                                try:
                                    dr2 = await frame.evaluate("""() => {
                                        const srcSet = new Set();
                                        document.querySelectorAll('a[href^="http"]').forEach(a => {
                                            const h = a.href || '';
                                            if (h.length < 500 &&
                                                !h.includes('chatgpt.com') && !h.includes('openai.com') &&
                                                !h.includes('oaiusercontent')) srcSet.add(h);
                                        });
                                        return { source_urls: Array.from(srcSet).slice(0, 30) };
                                    }""")
                                    if dr2 and dr2.get("source_urls"):
                                        # Union (preserve order) instead of replace —
                                        # the panel may render different URLs than the
                                        # pre-click DOM scrape (different ordering or
                                        # subset). Strict `>` would skip cases where
                                        # post-click count ties pre-click but the URLs
                                        # are objectively different.
                                        seen_u = set(result.get("source_urls") or [])
                                        unioned = list(result.get("source_urls") or [])
                                        for u in dr2["source_urls"]:
                                            if u not in seen_u:
                                                seen_u.add(u)
                                                unioned.append(u)
                                        if len(unioned) > result.get("sources", 0):
                                            result["source_urls"] = unioned[:30]
                                            result["sources"] = len(result["source_urls"])
                                except Exception as _re2:
                                    log(f"ChatGPT sources-panel re-scrape skipped: {_re2}", "DEBUG")
                        except Exception as _se:
                            log(f"ChatGPT sources-panel expand skipped: {_se}", "DEBUG")
                    # ── 2026-04-26 (v2): plan-checklist DOM walker + live-row click ──
                    # ChatGPT DR's plan checklist uses Tailwind <div>s (not role=checkbox /
                    # data-testid=task / bare <li>) so the v1 selectors missed iteration 1.
                    # v2: walk the checklist via verb-prefix + svg[class*=check|spin] heuristic,
                    # populate result.steps[] (full plan list, last 15) and result.progress
                    # (active-row label) directly. Click the live row IF NOT already
                    # aria-expanded, then re-scrape URLs scoped to the expanded subtree
                    # (no global host-page sweep). Opt out via DG_PLAN_ITEM_EXPAND=0.
                    if os.environ.get("DG_PLAN_ITEM_EXPAND", "1").lower() not in ("0", "false", "no"):
                        try:
                            walk = await frame.evaluate("""() => {
                                const out = { steps: [], live_label: '', clicked: false, already_expanded: false };
                                const VERB = /^(checking|searching|looking|browsing|investigating|analyzing|reading|exploring)\\b/i;
                                const all = Array.from(document.querySelectorAll('div, li, [role="listitem"], button, [role="button"]'));
                                const rows = [];
                                for (const el of all) {
                                    const t = (el.innerText || '').trim();
                                    if (!t || t.length < 4 || t.length > 220) continue;
                                    const hasCheck = !!el.querySelector('svg[class*="check"], svg[data-icon*="check"]');
                                    const hasSpin  = !!el.querySelector('svg[class*="spin"], svg[class*="loader"], [class*="animate-spin"]');
                                    const verbHit  = VERB.test(t);
                                    if (!verbHit && !hasCheck && !hasSpin) continue;
                                    const key = t.slice(0, 60);
                                    if (rows.find(r => r.key === key)) continue;
                                    rows.push({ el, t, hasCheck, hasSpin, verbHit, key });
                                }
                                out.steps = rows.map(r => r.t.slice(0, 200)).slice(-15);
                                const live = rows.find(r => r.hasSpin) ||
                                             rows.find(r => r.verbHit && !r.hasCheck);
                                if (live) {
                                    out.live_label = live.t.slice(0, 160);
                                    const expanded = live.el.getAttribute('aria-expanded');
                                    if (expanded === 'true') {
                                        out.already_expanded = true;
                                    } else {
                                        live.el.click();
                                        out.clicked = true;
                                    }
                                }
                                return out;
                            }""")
                            if walk:
                                if walk.get("steps"):
                                    result["steps"] = walk["steps"]
                                if walk.get("live_label"):
                                    result["progress"] = walk["live_label"]
                                if walk.get("clicked"):
                                    log(f'[ChatGPT] plan-item live-row clicked: "{walk.get("live_label","")}"')
                                    await asyncio.sleep(1.0)
                                if walk.get("clicked") or walk.get("already_expanded"):
                                    try:
                                        dr3 = await frame.evaluate("""() => {
                                            const expanded = document.querySelector('[aria-expanded="true"]');
                                            const root = expanded || document;
                                            const srcSet = new Set();
                                            root.querySelectorAll('a[href^="http"]').forEach(a => {
                                                const h = a.href || '';
                                                if (h.length < 500 &&
                                                    !h.includes('chatgpt.com') && !h.includes('openai.com') &&
                                                    !h.includes('oaiusercontent')) srcSet.add(h);
                                            });
                                            return { source_urls: Array.from(srcSet).slice(0, 50) };
                                        }""")
                                        if dr3 and dr3.get("source_urls"):
                                            seen3 = set(result.get("source_urls") or [])
                                            unioned3 = list(result.get("source_urls") or [])
                                            for u in dr3["source_urls"]:
                                                if u not in seen3:
                                                    seen3.add(u)
                                                    unioned3.append(u)
                                            if len(unioned3) > len(result.get("source_urls") or []):
                                                result["source_urls"] = unioned3[:30]
                                                result["sources"] = len(result["source_urls"])
                                    except Exception as _re3:
                                        log(f"ChatGPT plan-item re-scrape skipped: {_re3}", "DEBUG")
                        except Exception as _pe:
                            log(f"ChatGPT plan-item walker skipped: {_pe}", "DEBUG")
                    break
        except Exception as _fe:
            log(f"ChatGPT frames iteration skipped: {_fe}", "DEBUG")

        # ---- Synthesize steps if iframe didn't provide any
        if not result.get("steps"):
            synth = []
            if result.get("thinking"):
                synth.append("Extended Thinking: " + result["thinking"][:100])
            hosts = set()
            for u in result.get("source_urls", []):
                try:
                    from urllib.parse import urlparse
                    h = urlparse(u).hostname or ""
                    if h.startswith("www."):
                        h = h[4:]
                    if h:
                        hosts.add(h)
                except Exception:
                    pass
            for h in list(hosts)[:5]:
                synth.append(f"Researching {h}")
            if result.get("sections"):
                synth.append(f"Writing: {result['sections'][-1]}")
            if result.get("partial_text_len", 0) > 3000:
                synth.append(f"Generating brief: {round(result['partial_text_len']/1000)}k chars")
            result["steps"] = synth

        if result.get("steps") and not result.get("progress"):
            result["progress"] = result["steps"][-1]

        # Plan line (sections as outline)
        if len(result.get("sections", [])) >= 2 and not result.get("plan"):
            result["plan"] = "Research outline: " + " \u2192 ".join(result["sections"][:5])

        # ---- Final status resolution
        has_stop = result.pop("has_stop_btn", False)
        dr_active = result.pop("dr_active", False)
        dr_done_text = result.pop("dr_done_text", False)
        partial = result.get("partial_text_len", 0)
        if has_stop or dr_active:
            result["status"] = "generating"
            result["phase"] = "deep_research" if dr_active else "researching"
            if not result.get("progress"):
                result["progress"] = "Deep Research in progress"
        elif dr_done_text and partial > 100:
            result["status"] = "complete"
            result["phase"] = "done"
        elif partial > 100:
            # Partial content but no active/done signal — call it complete (historical behavior)
            result["status"] = "complete"
            result["phase"] = "done"
        else:
            result["status"] = "idle"
            result["phase"] = "waiting"

        return result
    except Exception as e:
        log(f"ChatGPT scrape failed (selectors may need update): {e}", "WARN")
        return {"status": "scrape_error", "progress": "Selector mismatch — ChatGPT UI may have changed", "sources": 0, "partial_text_len": 0}


async def _open_chatgpt_activity_panel(page):
    """Click the collapsed activity strip (e.g. 'Looking into Hermes... 196 searches')
    in ChatGPT Deep Research so the side panel with full step list + source URLs
    slides out.

    Robust selector (2026-04-26 v2): walks ALL elements (not just buttons —
    ChatGPT renders the strip as a styled <div> with imperatively-bound click
    handlers, so the v1 narrow `button, [role="button"]` selector matched 0
    candidates and silently no-op'd across 3 user runs). Recurses into Shadow
    DOM. Dispatches the full pointer/mouse event chain (pointerdown → mousedown
    → pointerup → mouseup → click) instead of bare `.click()` so React's
    synthetic listeners fire. Tries the leaf element then 5 ancestors.

    Returns dict with `found`, `candidates` (count of text-matched nodes),
    `clicked`, `alreadyExpanded`, `label`, `clickedTag`. Caller uses
    `_verify_chatgpt_panel_open(page)` 2s post-click to confirm side panel
    actually rendered (mitigates silent click failures)."""
    JS = """() => {
        // searches | sources | results — covers all observed badge wordings
        const COUNT = /\\b\\d+\\s+(?:searches?|sources?|results?)\\b/i;
        // Verb-only fallback for Pro+ET strips that haven't materialized a count yet.
        // Includes "thinking"/"reasoning" because Pro+ET shows those before swapping
        // to site-fetch verbs ("Reading <site>", "Visiting <url>") mid-stream.
        const VERB_ONLY = /^(thinking|reasoning|searching|looking|browsing|investigating|analyzing|reading|exploring|checking|visiting|researching)\\b/i;
        const seen = new WeakSet();
        const hits = [];
        function walk(root) {
            if (!root || seen.has(root)) return;
            seen.add(root);
            let nodes;
            try { nodes = root.querySelectorAll('*'); } catch (e) { return; }
            if (nodes.length > 8000) return;  // bail on absurd page sizes
            for (const el of nodes) {
                if (el.shadowRoot) walk(el.shadowRoot);
                const t = (el.innerText || el.textContent || '').trim();
                if (!t || t.length < 4 || t.length > 300) continue;
                const matchesCount = COUNT.test(t);
                const matchesVerb  = VERB_ONLY.test(t);
                if (!matchesCount && !matchesVerb) continue;
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                // count-badge matches rank ahead of verb-only (more specific)
                hits.push({ el, top: r.top, len: t.length, hasCount: matchesCount });
            }
        }
        walk(document);
        if (!hits.length) return { found: false, candidates: 0 };
        // count-badge wins (more specific), then lowest-on-page, then shortest text
        hits.sort((a, b) => (b.hasCount - a.hasCount) || (b.top - a.top) || (a.len - b.len));
        const target = hits[0].el;
        const label = (target.innerText || target.textContent || '').trim().slice(0, 160);
        // aria-expanded check up the chain — skip re-click if already open
        let probe = target;
        for (let i = 0; i < 6 && probe; i++) {
            if (probe.getAttribute && probe.getAttribute('aria-expanded') === 'true') {
                return { found: true, alreadyExpanded: true, label, candidates: hits.length };
            }
            probe = probe.parentElement;
        }
        // parent-chain dispatch loop — try leaf, then up to 5 ancestors
        const tries = [];
        let node = target;
        for (let i = 0; i < 6 && node; i++) {
            tries.push(node);
            node = node.parentElement;
        }
        let clickedTag = '';
        let lastErr = '';
        for (const n of tries) {
            try {
                const r = n.getBoundingClientRect();
                const x = r.left + r.width / 2, y = r.top + r.height / 2;
                const opts = { bubbles: true, cancelable: true, view: window,
                               clientX: x, clientY: y, button: 0 };
                // Full event chain — covers React onPointerDown/onMouseDown/onClick
                n.dispatchEvent(new MouseEvent('pointerdown', opts));
                n.dispatchEvent(new MouseEvent('mousedown',  opts));
                n.dispatchEvent(new MouseEvent('pointerup',  opts));
                n.dispatchEvent(new MouseEvent('mouseup',    opts));
                n.dispatchEvent(new MouseEvent('click',      opts));
                clickedTag = (n.tagName || '') +
                             (n.getAttribute && n.getAttribute('role')
                                 ? `[${n.getAttribute('role')}]` : '');
                break;
            } catch (e) { lastErr = String(e); continue; }
        }
        return { found: true, clicked: !!clickedTag, label,
                 candidates: hits.length, clickedTag, error: lastErr };
    }"""
    try:
        res = await page.evaluate(JS)
        if res and res.get("found"):
            return res
    except Exception:
        pass
    try:
        for frame in page.frames:
            try:
                src = (frame.url or "").lower()
            except Exception:
                continue
            if not src:
                continue
            if ("deep_research" in src or "oaiusercontent" in src or
                    "web-sandbox.oaiusercontent" in src):
                try:
                    res = await frame.evaluate(JS)
                    if res and res.get("found"):
                        return res
                except Exception:
                    continue
    except Exception:
        pass
    return {"found": False, "candidates": 0}


async def _verify_chatgpt_panel_open(page):
    """Returns True if a wide side panel is now visible on the right side of
    the ChatGPT DR viewport. Used post-click to detect silent click failures.

    Heuristic: an <aside> / [role="complementary"] / [aria-label*="source"i]
    / [class*="panel"] element with width >= 280px and at least one URL or
    numbered step row inside."""
    JS = """() => {
        const sels = [
            'aside', '[role="complementary"]', '[role="region"]',
            '[aria-label*="source" i]', '[aria-label*="research" i]',
            '[class*="panel" i][class*="side" i]',
            '[class*="research" i][class*="panel" i]'
        ];
        for (const sel of sels) {
            try {
                for (const el of document.querySelectorAll(sel)) {
                    const r = el.getBoundingClientRect();
                    if (r.width < 280 || r.height < 200) continue;
                    if (r.right < window.innerWidth * 0.55) continue;  // must be on right side
                    const inner = (el.innerText || '').trim();
                    if (inner.length < 50) continue;
                    const hasUrl = !!el.querySelector('a[href*="http"]');
                    const hasList = !!el.querySelector('ol > li, ul > li');
                    if (hasUrl || hasList) return true;
                }
            } catch (e) {}
        }
        return false;
    }"""
    try:
        ok = await page.evaluate(JS)
        if ok:
            return True
    except Exception:
        pass
    try:
        for frame in page.frames:
            try:
                src = (frame.url or "").lower()
            except Exception:
                continue
            if "oaiusercontent" in src or "deep_research" in src:
                try:
                    ok = await frame.evaluate(JS)
                    if ok:
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


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
            // Sources — Gemini Deep Research shows sources in research panel + response
            const srcSet = new Set();
            document.querySelectorAll(
                '.source-card, .citation, [data-source], .web-result, ' +
                '.research-source, [class*="source"], [class*="citation"], ' +
                'a[href*="http"]:not([href*="google.com/gemini"]):not([href*="accounts.google"])'
            ).forEach(s => {
                const a = s.querySelector ? s.querySelector('a') : s;
                const href = a?.href || '';
                if (href.startsWith('http') && href.length < 500) srcSet.add(href);
                else if (!href && s.innerText) srcSet.add(s.innerText.substring(0, 150));
            });
            r.source_urls = Array.from(srcSet).slice(0, 30);
            r.sources = r.source_urls.length;
            // Response sections
            const headings = document.querySelectorAll(
                'message-content h1, message-content h2, message-content h3, ' +
                '.model-response-text h1, .model-response-text h2, .model-response-text h3, ' +
                '[class*="response"] h1, [class*="response"] h2'
            );
            r.sections = Array.from(headings).map(h => h.innerText.substring(0, 80)).filter(s => s.length > 1);
            // Partial text
            const responses = document.querySelectorAll('message-content, .model-response-text');
            if (responses.length > 0) r.partial_text_len = responses[responses.length-1].innerText.length;
            // Status — robust stop button detection (multiple strategies)
            let isActive = false;
            // 1. aria-label selectors (multiple patterns)
            const stopSels = 'button[aria-label="Stop"], button[aria-label*="stop"], button[aria-label="Cancel"], button[title*="Stop"]';
            if (document.querySelector(stopSels)) isActive = true;
            // 2. Text-based: any button with "Stop" text
            if (!isActive) {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    const txt = (b.textContent || '').trim().toLowerCase();
                    if (txt === 'stop' || txt === 'stop generating' || txt === 'cancel') { isActive = true; break; }
                }
            }
            // 3. Streaming attribute (Gemini marks actively streaming content)
            if (!isActive && document.querySelector('[data-is-streaming="true"], .loading-indicator, .streaming')) isActive = true;
            // 4. Animation detection (spinning/pulsing elements indicate active work)
            if (!isActive) {
                const animated = document.querySelectorAll('[class*="animate"], [class*="spin"], [class*="pulse"], [class*="loading"]');
                for (const el of animated) {
                    const cs = window.getComputedStyle(el);
                    if (cs.animationName && cs.animationName !== 'none' && el.offsetParent !== null) { isActive = true; break; }
                }
            }
            // 5. Research progress panel still showing active steps
            if (!isActive && r.steps.length > 0) {
                const lastStep = r.steps[r.steps.length - 1].toLowerCase();
                if (lastStep.includes('searching') || lastStep.includes('reading') || lastStep.includes('analyzing') || lastStep.includes('browsing')) isActive = true;
            }
            // Planning-gate: if "Start research" button is visible, Gemini has
            // produced a plan but research hasn't started — do NOT mark complete
            // even if r.partial_text_len > 0 (that text is the plan, not output).
            let hasStartBtn = false;
            const allBtns = document.querySelectorAll('button');
            for (const b of allBtns) {
                const txt = (b.textContent || '').trim().toLowerCase();
                if (txt === 'start research' || txt.includes('start research')) { hasStartBtn = true; break; }
            }
            if (hasStartBtn) {
                r.status = 'generating';
                r.phase = 'planning';
                if (!r.progress) r.progress = 'Research plan ready — awaiting Start';
            } else {
                r.status = isActive ? 'generating' : (r.partial_text_len > 0 ? 'complete' : 'idle');
                r.phase = isActive ? 'researching' : (r.steps.length > 0 ? 'researching' : (r.plan ? 'planning' : (r.partial_text_len > 0 ? 'done' : 'waiting')));
            }
            return r;
        }""")
    except Exception as e:
        log(f"Gemini scrape failed (selectors may need update): {e}", "WARN")
        return {"status": "scrape_error", "progress": "Selector mismatch — Gemini UI may have changed", "sources": 0, "partial_text_len": 0}


async def scrape_progress_claude(page):
    """Scrape Claude's current research progress — rich data for web app.

    Claude Research (2026) shows:
      - "Stop research" button (not "Stop Response") while active
      - "N sources and counting" text while gathering sources
      - "Research completed in Xm" card header when done
      - Research renders inside a card/artifact panel, not main chat stream
    We detect these text markers as primary activity signals."""
    try:
        return await page.evaluate("""() => {
            const r = {
                status: 'unknown', phase: '', progress: '', thinking: '',
                sources: 0, source_urls: [], sections: [], steps: [],
                tool_uses: [], partial_text_len: 0, plan: '', model: '', title: ''
            };
            // Conversation title
            const ctitle = document.querySelector('[data-conversation-title], .conversation-title, header h1, h1.truncate, [data-testid="conversation-title"]');
            if (ctitle) r.title = ctitle.innerText.substring(0, 100);
            else if (document.title) r.title = document.title.replace(/ - Claude$/, '').replace(/^Claude$/, '').substring(0, 100);
            // Model info
            const modelEl = document.querySelector('.model-selector, [data-testid="model-name"]');
            if (modelEl) r.model = modelEl.innerText.substring(0, 50);
            // Thinking content
            const thinking = document.querySelector('[data-is-thinking="true"], .thinking-content, .thinking-block');
            if (thinking) r.thinking = thinking.innerText.substring(0, 500);

            // ---- Text-based markers (Claude Research surfaces activity as text, not attributes)
            const bodyText = document.body?.innerText || '';
            const bodyLower = bodyText.toLowerCase();
            // "N sources and counting" → research actively gathering
            const srcCountM = bodyText.match(/(\\d[\\d,]*)\\s+sources?\\s+and\\s+counting/i);
            const liveSrcCount = srcCountM ? parseInt(srcCountM[1].replace(/,/g, ''), 10) : 0;
            // "Research completed in Xm" → research done
            // 2026-04-26: matches BOTH "research completed in 5m" (legacy)
            // AND "Research complete · 553 sources · 24m 41s" (modern 2026).
            const doneM = bodyText.match(/research\\s+complete(?:d)?(?:\\s+in)?(?:[\\s·•—\\-]+\\d[\\d,]*\\s+sources?)?(?:[\\s·•—\\-]+\\d+(?:[hms]|\\s*(?:hour|min|sec)))?/i);
            const researchDone = !!doneM;

            // ---- Tool uses (Research tool, web_search, browse, etc.)
            const tools = document.querySelectorAll(
                '.tool-use-content, [data-tool-name], .tool-result, ' +
                '[class*="tool-use"], [class*="tool_use"], [data-testid*="tool"], ' +
                '.font-claude-message [class*="border"][class*="rounded"]'
            );
            r.tool_uses = Array.from(tools).map(t => {
                const name = t.getAttribute('data-tool-name') || '';
                const txt = (t.innerText || '').substring(0, 200);
                return name ? `${name}: ${txt}` : txt;
            }).filter(t => t.length > 3);

            // ---- Sources — citations, tool-result links, artifact links
            const srcSet = new Set();
            document.querySelectorAll('.font-claude-message a[href*="http"], .contents a[href*="http"]').forEach(a => {
                const href = a.href || '';
                if (href.startsWith('http') && !href.includes('claude.ai') && !href.includes('anthropic.com'))
                    srcSet.add(href);
            });
            document.querySelectorAll('[class*="tool"] a[href], .tool-result a[href]').forEach(a => {
                if (a.href?.startsWith('http') && !a.href.includes('claude.')) srcSet.add(a.href);
            });
            document.querySelectorAll('aside a[href*="http"], [class*="artifact"] a[href*="http"]').forEach(a => {
                if (a.href?.startsWith('http') && !a.href.includes('claude.')) srcSet.add(a.href);
            });
            // Broad research-card link sweep: any http link inside an element whose class/text
            // mentions "research" (research report lives inside card wrappers with dynamic classes)
            document.querySelectorAll('[class*="research"] a[href*="http"], [data-testid*="research"] a[href*="http"]').forEach(a => {
                if (a.href?.startsWith('http') && !a.href.includes('claude.')) srcSet.add(a.href);
            });
            r.source_urls = Array.from(srcSet).slice(0, 30);
            r.sources = r.source_urls.length;
            // If DOM didn't surface individual source links but Claude shows "N sources" text, trust the text count
            if (r.sources === 0 && liveSrcCount > 0) r.sources = liveSrcCount;

            // ---- Sections — headings across conversation, artifact, and research card
            const headings = document.querySelectorAll(
                '.font-claude-message h1, .font-claude-message h2, .font-claude-message h3, ' +
                '.contents h1, .contents h2, .contents h3, ' +
                'aside h1, aside h2, aside h3, ' +
                '[class*="artifact"] h1, [class*="artifact"] h2, ' +
                '[class*="research"] h1, [class*="research"] h2, [class*="research"] h3'
            );
            r.sections = Array.from(headings).map(h => (h.innerText || '').substring(0, 80)).filter(s => s.length > 1);

            // ---- Partial text — conversation + artifact + research card
            let textLen = 0;
            const msgs = document.querySelectorAll('.font-claude-message, .contents .prose');
            if (msgs.length > 0) textLen = msgs[msgs.length-1].innerText.length;
            const artifact = document.querySelector('aside .prose, aside [class*="content"], [class*="artifact-panel"] .prose');
            if (artifact) textLen = Math.max(textLen, artifact.innerText.length);
            // Research card container text (major content host when "Research" tool is used)
            const researchCard = document.querySelector('[class*="research-card"], [data-testid*="research"], [class*="research-report"]');
            if (researchCard) textLen = Math.max(textLen, (researchCard.innerText || '').length);
            r.partial_text_len = textLen;

            // ---- 2026-04-26 v3: extract artifact-1 CARD preview text BEFORE
            // the side panel opens. The card sits in the assistant message in
            // the conversation column with class containing "artifact" — title
            // + first ~5 visible checklist rows are visible here. Currently the
            // existing scrape only reads <a href> links from these wrappers;
            // we now also extract the card body text so steps[] / progress
            // populate from the first poll, not just after iter-#3 panel-open.
            try {
                const artifactCards = document.querySelectorAll(
                    '.font-claude-message [class*="artifact"]'
                );
                const cardLines = [];
                let cardTitle = '';
                for (const c of artifactCards) {
                    const t = (c.innerText || '').trim();
                    if (!t || t.length < 10) continue;
                    const lines = t.split('\\n').map(s => s.trim())
                                   .filter(s => s.length > 3 && s.length < 200);
                    if (!cardTitle && lines.length) cardTitle = lines[0];
                    for (const ln of lines.slice(1, 8)) cardLines.push(ln);
                }
                if (cardTitle && !r.title) r.title = cardTitle.slice(0, 100);
                cardLines.slice(0, 6).forEach(ln => r.steps.push(ln));
                if (cardLines.length > 0 && !r.progress) {
                    r.progress = cardLines[cardLines.length - 1];
                }
            } catch(e) {}

            // ---- 2026-04-26 v4: live panel walker — after the artifact panel
            // opens (aside / artifact-panel mount), the panel root contains the
            // full live checklist. Wide-net VERB+check+spin walker matches the
            // ChatGPT P1 host-panel pattern; rows from the panel beat the card
            // preview (panel is fresher) and the spinner row drives r.progress.
            try {
                const VERB2 = /^(checking|searching|looking|browsing|investigating|analyzing|reading|exploring|visiting|researching|thinking|reasoning)\\b/i;
                const panelRoots = document.querySelectorAll('aside, [class*="artifact-panel"], [class*="research-panel"]');
                const panelSeen = new Set();
                const panelRows = [];
                let panelLive = '';
                for (const root of panelRoots) {
                    const pr = root.getBoundingClientRect();
                    if (pr.width < 280 || pr.height < 200) continue;
                    const rowEls = Array.from(root.querySelectorAll('div, li, [role="listitem"], button, [role="button"], p'));
                    for (const el of rowEls) {
                        const t = (el.innerText || '').trim();
                        if (!t || t.length < 4 || t.length > 220) continue;
                        const hasCheck = !!el.querySelector('svg[class*="check"], svg[data-icon*="check"]');
                        const hasSpin  = !!el.querySelector('svg[class*="spin"], svg[class*="loader"], [class*="animate-spin"]');
                        const verbHit  = VERB2.test(t);
                        if (!verbHit && !hasCheck && !hasSpin) continue;
                        const key = t.slice(0, 60);
                        if (panelSeen.has(key)) continue;
                        panelSeen.add(key);
                        panelRows.push({ t: t.slice(0, 200), hasSpin, hasCheck, verbHit });
                        if (hasSpin && !panelLive) panelLive = t.slice(0, 160);
                    }
                }
                if (panelRows.length > 0) {
                    const panelSteps = panelRows.map(x => x.t).slice(-15);
                    r.steps = panelSteps.concat(r.steps);
                    if (panelLive) r.progress = panelLive;
                    else r.progress = panelRows[panelRows.length - 1].t.slice(0, 160);
                }
            } catch(e) {}

            // ---- Steps: synthesize from tool_uses + live markers + sources
            if (r.thinking) r.steps.push('Extended Thinking: ' + r.thinking.substring(0, 100));
            r.tool_uses.slice(-5).forEach(t => {
                const brief = t.substring(0, 120);
                r.steps.push(brief.toLowerCase().includes('earch') ? 'Searching: ' + brief : brief);
            });
            if (liveSrcCount > 0) r.steps.push(`Gathering sources (${liveSrcCount} and counting)`);
            const cHosts = new Set();
            r.source_urls.forEach(u => { try { cHosts.add(new URL(u).hostname.replace('www.', '')); } catch(e) {} });
            Array.from(cHosts).slice(0, 5).forEach(h => r.steps.push('Browsing ' + h));
            if (r.sections.length > 0) r.steps.push('Building: ' + r.sections[r.sections.length - 1]);
            if (r.partial_text_len > 3000) r.steps.push('Artifact: ' + Math.round(r.partial_text_len / 1000) + 'k chars');
            if (researchDone) r.steps.push('Research completed');

            if (r.tool_uses.length > 0) r.progress = r.tool_uses[r.tool_uses.length - 1].substring(0, 200);
            else if (r.steps.length > 0) r.progress = r.steps[r.steps.length - 1];
            else if (liveSrcCount > 0) r.progress = `${liveSrcCount} sources and counting`;

            // Plan
            if (r.sections.length >= 2) r.plan = 'Research structure: ' + r.sections.slice(0, 5).join(' \\u2192 ');

            // ---- Status resolution (multi-strategy)
            // 1. "Stop research" / "Stop" button — primary active signal
            let hasStop = false;
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const txt = (b.textContent || '').trim().toLowerCase();
                const al  = (b.getAttribute('aria-label') || '').toLowerCase();
                if (txt === 'stop' || txt === 'stop generating' || txt === 'stop research' ||
                    txt === 'stop researching' ||
                    al.includes('stop response') || al.includes('stop research') ||
                    al.includes('stop generating')) { hasStop = true; break; }
            }
            // 2. Streaming DOM markers
            if (!hasStop && document.querySelector('[data-is-streaming="true"], .streaming, [class*="animate-pulse"]')) hasStop = true;
            // 3. "sources and counting" → still gathering (active)
            if (!hasStop && liveSrcCount > 0) hasStop = true;
            // 4. Body keyword sweep for active research verbs
            if (!hasStop) {
                const activeKws = ['searching the web', 'analyzing sources', 'reading sources',
                                   'browsing', 'conducting research', 'gathering information'];
                if (activeKws.some(kw => bodyLower.includes(kw))) hasStop = true;
            }

            // Resolve status — completion text trumps stale "active" signals
            if (researchDone && !hasStop) {
                r.status = 'complete'; r.phase = 'done';
            } else if (hasStop) {
                r.status = 'generating';
                r.phase = r.thinking ? 'thinking' : (r.tool_uses.length > 0 || liveSrcCount > 0 ? 'researching' : 'generating');
            } else if (r.partial_text_len > 0 || r.sources > 0) {
                r.status = 'complete'; r.phase = 'done';
            } else {
                r.status = 'idle'; r.phase = 'waiting';
            }
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


# ── Per-Agent Completion Detectors (Playwright-only) ──────────────────────────
# Atomic single-shot detectors for the round-robin loop. Each returns
# (done: bool, reason: str). Reason is a short string for logging/telemetry.
# The caller tracks "2 consecutive polls" semantics where required — detectors
# just report the current signal snapshot from a single poll.
#
# Rules (locked 2026-04 with Phase 2 orchestration overhaul):
#   ChatGPT: no Stop (host + iframe) AND ("Research completed" text OR partial>5000)
#   Claude : no Stop/"sources and counting" AND
#            (artifacts>=2 OR done-text OR (partial>8000 AND summary/conclusion heading))
#   Gemini : no Start-research AND no Stop AND
#            (Share/Export visible OR (partial>5000 AND no active keywords))

async def detect_completion_chatgpt(page):
    """ChatGPT Deep Research completion detector. Playwright-only.
    Returns (done, reason, snap) where snap = {text_len, sources, steps}.

    2026-04-25 strictness rewrite: detector returns done=True ONLY when:
      • Stop button is gone (host AND iframe)
      • "Thought for X seconds" badge present (definitive done marker)
    The previous `partial_len > 5000` fallback was a known false-positive
    path (fired mid-stream during long research). Removed entirely. The
    caller is responsible for the 2-cycle flatness gate (text/sources/steps
    all flat across 2 polling cycles) before extracting — we only report
    the snapshot here, never decide on flatness."""
    try:
        host = await page.evaluate("""() => {
            let hasStop = !!document.querySelector(
                'button[aria-label="Stop generating"], button[aria-label*="Stop"], ' +
                'button[data-testid="stop-button"], button[data-testid*="stop"]'
            );
            if (!hasStop) {
                for (const b of document.querySelectorAll('button')) {
                    const t = (b.textContent || '').trim().toLowerCase();
                    if (t === 'stop' || t === 'stop generating' || t === 'stop research') {
                        hasStop = true; break;
                    }
                }
            }
            const bl = (document.body?.innerText || '');
            // "Thought for X seconds" badge — renders only AFTER thinking
            // phase completes. With Stop button gone + this badge present,
            // we're as confident as we can be that DR is fully settled.
            const thoughtFor = /thought for\\s+\\d/i.test(bl);
            // 2026-04-26 backup: same modern marker Claude uses. Covers the case
            // where ChatGPT renames the badge or runs a non-thinking-mode DR
            // variant where "Thought for X" never appears. Either signal counts.
            const researchDone = /research\\s+complete(?:d)?(?:[\\s·•—\\-]+\\d[\\d,]*\\s+sources?)?/i.test(bl);
            const doneMarker = thoughtFor || researchDone;
            const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
            const hostLen = msgs.length ? msgs[msgs.length-1].innerText.length : 0;
            // Sources count: external citation links anywhere on the page
            const sources = document.querySelectorAll('a[href^="http"][target="_blank"]').length;
            // Steps: research card list items (the rotating step list)
            const steps = document.querySelectorAll(
                '[class*="research"] li, [class*="step"], [class*="task"]'
            ).length;
            return { hasStop, thoughtFor, researchDone, doneMarker, hostLen, sources, steps };
        }""")

        iframe_stop = False
        iframe_thought = False
        iframe_len = 0
        iframe_sources = 0
        iframe_steps = 0
        try:
            for frame in page.frames:
                try:
                    src = (frame.url or "").lower()
                except Exception:
                    continue
                if not src:
                    continue
                if ("deep_research" in src or "oaiusercontent" in src):
                    try:
                        data = await frame.evaluate("""() => {
                            let hasStop = false;
                            for (const b of document.querySelectorAll('button')) {
                                const t = (b.textContent || '').trim().toLowerCase();
                                const al = (b.getAttribute('aria-label') || '').toLowerCase();
                                if (t === 'stop' || t === 'stop research' ||
                                    al.includes('stop')) { hasStop = true; break; }
                            }
                            const bl = (document.body?.innerText || '');
                            const thoughtFor = /thought for\\s+\\d/i.test(bl);
                            const researchDone = /research\\s+complete(?:d)?(?:[\\s·•—\\-]+\\d[\\d,]*\\s+sources?)?/i.test(bl);
                            const doneMarker = thoughtFor || researchDone;
                            const sources = document.querySelectorAll(
                                'a[href^="http"][target="_blank"]'
                            ).length;
                            const steps = document.querySelectorAll(
                                '[class*="research"] li, [class*="step"], [class*="task"]'
                            ).length;
                            return { hasStop, thoughtFor, researchDone, doneMarker, len: bl.length, sources, steps };
                        }""")
                        if data:
                            iframe_stop = bool(data.get("hasStop"))
                            iframe_thought = bool(data.get("doneMarker"))
                            iframe_len = int(data.get("len") or 0)
                            iframe_sources = int(data.get("sources") or 0)
                            iframe_steps = int(data.get("steps") or 0)
                    except Exception:
                        pass
                    break
        except Exception:
            pass

        has_stop = host["hasStop"] or iframe_stop
        # done_marker = ("Thought for X seconds" badge OR "Research complete · N sources" text).
        # Either is enough — non-thinking DR variants don't produce the badge,
        # and renamed-badge variants don't match /thought for \d+/.
        has_done_marker = bool(host.get("doneMarker")) or iframe_thought
        which_marker = ("thought_for" if host.get("thoughtFor") or iframe_thought
                        else "research_complete" if host.get("researchDone") else "")
        partial_len = max(int(host.get("hostLen") or 0), iframe_len)
        sources = max(int(host.get("sources") or 0), iframe_sources)
        steps = max(int(host.get("steps") or 0), iframe_steps)
        snap = {"text_len": partial_len, "sources": sources, "steps": steps}

        if has_stop:
            return (False, f"stop_btn_present (text={partial_len}, src={sources}, st={steps})", snap)
        if not has_done_marker:
            return (False, f"no_done_marker (Thought-for badge AND Research-complete text both missing)", snap)
        return (True, f"no_stop + done_marker={which_marker}", snap)
    except Exception as e:
        return (False, f"detect_error: {e}", {})


async def detect_completion_claude(page):
    """Claude Research completion detector. Playwright-only.
    Returns (done, reason, snap) where snap = {text_len, sources, steps}.

    2026-04-25 strictness rewrite: detector returns done=True ONLY when:
      • Stop button gone + no live "sources and counting" indicator
      • "research completed" text present OR research-card status='complete'
    Removed: artifacts>=2 fallback (Claude legitimately produces 2 artifacts
    pre-final), text_len>8000+heading fallback (mid-stream summary headings
    can match). Caller handles 2-cycle flatness."""
    try:
        data = await page.evaluate("""() => {
            let hasStop = false;
            for (const b of document.querySelectorAll('button')) {
                const txt = (b.textContent || '').trim().toLowerCase();
                const al  = (b.getAttribute('aria-label') || '').toLowerCase();
                if (txt === 'stop' || txt === 'stop generating' || txt === 'stop research' ||
                    txt === 'stop researching' ||
                    al.includes('stop response') || al.includes('stop research') ||
                    al.includes('stop generating')) { hasStop = true; break; }
            }
            if (!hasStop && document.querySelector(
                '[data-is-streaming="true"], .streaming, [class*="animate-pulse"]'
            )) hasStop = true;

            const bodyText = document.body?.innerText || '';
            // 2026-04-26: regex now matches BOTH "research completed in 5m"
            // (legacy) AND "Research complete · 553 sources · 24m 41s" (modern
            // 2026 layout). The middle separators are unicode bullets/dots/
            // hyphens. Sources/duration suffixes optional.
            const researchDone = /research\\s+complete(?:d)?(?:\\s+in)?(?:[\\s·•—\\-]+\\d[\\d,]*\\s+sources?)?(?:[\\s·•—\\-]+\\d+(?:[hms]|\\s*(?:hour|min|sec)))?/i.test(bodyText);
            const liveActive = /\\d[\\d,]*\\s+sources?\\s+and\\s+counting/i.test(bodyText);
            // Claude's research card flips status when streaming ends.
            // 2026-04-26: also accept TEXT-CONTENT match — Claude's modern
            // layout doesn't use [data-research-status]; the artifact card
            // shows "Research complete · N sources · Xm Ys" as visible text.
            let researchCardDone = !!document.querySelector(
                '[data-research-status="complete"], [data-research-state="done"]'
            );
            if (!researchCardDone) {
                researchCardDone = !!Array.from(
                    document.querySelectorAll('[class*="card"], [class*="artifact"], button, div[role="button"]')
                ).find(el => /research\\s+complete(?:d)?\\s*[\\s·•—\\-]/i.test(el.textContent || ''));
            }

            let textLen = 0;
            const msgs = document.querySelectorAll('.font-claude-message, .contents .prose');
            if (msgs.length > 0) textLen = msgs[msgs.length-1].innerText.length;
            const artifact = document.querySelector(
                'aside .prose, aside [class*="content"], [class*="artifact-panel"] .prose'
            );
            if (artifact) textLen = Math.max(textLen, artifact.innerText.length);
            const researchCard = document.querySelector(
                '[class*="research-card"], [data-testid*="research"], [class*="research-report"]'
            );
            if (researchCard) textLen = Math.max(textLen, (researchCard.innerText || '').length);

            const sources = document.querySelectorAll(
                '.font-claude-message a[href^="http"], aside a[href^="http"]'
            ).length;
            const steps = document.querySelectorAll(
                '[class*="research"] li, [class*="step"]'
            ).length;
            return { hasStop, researchDone, researchCardDone, liveActive,
                     textLen, sources, steps };
        }""")

        text_len = int(data.get("textLen") or 0)
        sources = int(data.get("sources") or 0)
        steps = int(data.get("steps") or 0)
        snap = {"text_len": text_len, "sources": sources, "steps": steps}

        if data.get("liveActive"):
            return (False, f"live_sources_counting", snap)
        if data.get("hasStop"):
            return (False, f"stop_btn_present (text={text_len})", snap)
        if not (data.get("researchDone") or data.get("researchCardDone")):
            return (False, f"no_done_marker (no research_complete text/card)", snap)
        return (True, f"no_stop + research_complete_marker", snap)
    except Exception as e:
        return (False, f"detect_error: {e}", {})


async def detect_completion_gemini(page):
    """Gemini Deep Research completion detector. Playwright-only.
    Returns (done, reason, snap) where snap = {text_len, sources, steps}.

    2026-04-25 strictness rewrite: done=True ONLY when:
      • Stop button gone + Start-research button gone (post-planning)
      • Share & Export button visible (definitive done — only renders
        after research finishes)
    Removed: text_len>5000+!active_kw fallback (transient no-active-keyword
    windows mid-stream caused false positives). Caller handles 2-cycle flat."""
    try:
        data = await page.evaluate("""() => {
            let hasStop = false;
            const stopSels = 'button[aria-label="Stop"], button[aria-label*="stop"], ' +
                             'button[aria-label="Cancel"], button[title*="Stop"]';
            if (document.querySelector(stopSels)) hasStop = true;
            if (!hasStop) {
                for (const b of document.querySelectorAll('button')) {
                    const txt = (b.textContent || '').trim().toLowerCase();
                    if (txt === 'stop' || txt === 'stop generating' || txt === 'cancel') {
                        hasStop = true; break;
                    }
                }
            }
            if (!hasStop && document.querySelector(
                '[data-is-streaming="true"], .loading-indicator, .streaming'
            )) hasStop = true;

            let hasStartBtn = false;
            for (const b of document.querySelectorAll('button')) {
                const txt = (b.textContent || '').trim().toLowerCase();
                if (txt === 'start research' || txt.includes('start research')) {
                    hasStartBtn = true; break;
                }
            }

            let hasShareExport = false;
            const shareKws = ['share & export', 'share and export'];
            for (const b of document.querySelectorAll('button, [role="button"]')) {
                const txt = (b.textContent || '').trim().toLowerCase();
                const al  = (b.getAttribute('aria-label') || '').toLowerCase();
                if (shareKws.some(k => txt === k || al.includes(k))) {
                    hasShareExport = true; break;
                }
                if (txt === 'share' || txt === 'export' ||
                    al === 'share' || al === 'export') {
                    hasShareExport = true; break;
                }
            }

            let textLen = 0;
            const responses = document.querySelectorAll('message-content, .model-response-text');
            if (responses.length > 0) textLen = responses[responses.length-1].innerText.length;

            const sources = document.querySelectorAll(
                'message-content a[href^="http"]'
            ).length;
            const steps = document.querySelectorAll(
                '[class*="research-step"], [class*="thought"]'
            ).length;
            return { hasStop, hasStartBtn, hasShareExport, textLen, sources, steps };
        }""")

        text_len = int(data.get("textLen") or 0)
        sources = int(data.get("sources") or 0)
        steps = int(data.get("steps") or 0)
        snap = {"text_len": text_len, "sources": sources, "steps": steps}

        if data.get("hasStartBtn"):
            return (False, "start_research_btn_visible (pre-research)", snap)
        if data.get("hasStop"):
            return (False, f"stop_btn_present (text={text_len})", snap)
        if not data.get("hasShareExport"):
            return (False, f"no_done_marker (Share/Export button missing)", snap)
        return (True, f"no_stop + share_export_visible", snap)
    except Exception as e:
        return (False, f"detect_error: {e}", {})


DETECT_FNS = {
    "ChatGPT": detect_completion_chatgpt,
    "Gemini":  detect_completion_gemini,
    "Claude":  detect_completion_claude,
}


# ── Claude Artifact DOM Helpers ──────────────────────────────────────────────

async def _count_claude_artifacts(page):
    """Count artifact preview cards in Claude conversation. Returns int.
    2026-04-26: extended selectors for the modern Research card layout —
    aria-label="Open the artifact", a[href*="/artifacts/"] direct links,
    role=button rounded card divs, plus a TEXT-content fallback that
    finds buttons whose text contains "Research complete" or starts with
    a research-card-style prefix (e.g. "OpenClaw and OpenShell research").
    """
    try:
        return await page.evaluate("""() => {
            const selectors = [
                'button[data-testid*="artifact"]',
                '[data-testid*="artifact-preview"]',
                '.artifact-card', '.artifact-preview',
                'button[data-artifact-id]',
                '[class*="artifact"][role="button"]',
                'button[aria-label*="Open the artifact"]',
                'button[aria-label*="research"]',
                'a[href*="/artifacts/"]',
                'div[role="button"][class*="rounded"][class*="border"]',
            ];
            let total = 0;
            for (const sel of selectors) {
                const found = document.querySelectorAll(sel);
                if (found.length > 0) { total = Math.max(total, found.length); }
            }
            // Text-content fallback: any clickable element that contains the
            // modern "Research complete · N sources · Xm Ys" marker.
            const textHits = Array.from(document.querySelectorAll(
                '.font-claude-message button, .font-claude-message [role="button"], ' +
                'button, [role="button"]'
            )).filter(el => /research\\s+complete(?:d)?\\s*[\\s·•—\\-]/i.test(el.textContent || ''));
            total = Math.max(total, textHits.length);
            // Legacy fallback: document-like inline cards in assistant messages
            if (total === 0) {
                const cards = document.querySelectorAll(
                    '.font-claude-message button[class*="block"], ' +
                    '.font-claude-message [class*="artifact"], ' +
                    '[data-is-streaming] button[class*="w-full"]'
                );
                total = cards.length;
            }
            return total;
        }""")
    except Exception as e:
        log(f"Artifact count failed: {e}", "WARN")
        return 0


async def _click_claude_artifact(page, index=0):
    """Click the Nth artifact card (0-indexed). Returns True if clicked.
    2026-04-26: same modernized selectors as _count_claude_artifacts."""
    try:
        return await page.evaluate(f"""(idx) => {{
            const selectors = [
                'button[data-testid*="artifact"]',
                '[data-testid*="artifact-preview"]',
                '.artifact-card', '.artifact-preview',
                'button[data-artifact-id]',
                '[class*="artifact"][role="button"]',
                'button[aria-label*="Open the artifact"]',
                'button[aria-label*="research"]',
                'a[href*="/artifacts/"]',
                'div[role="button"][class*="rounded"][class*="border"]',
            ];
            let cards = [];
            for (const sel of selectors) {{
                const found = document.querySelectorAll(sel);
                if (found.length > 0) {{ cards = Array.from(found); break; }}
            }}
            if (!cards.length) {{
                // Text-content fallback: clickable element with "Research complete · …"
                const textHits = Array.from(document.querySelectorAll(
                    '.font-claude-message button, .font-claude-message [role="button"], ' +
                    'button, [role="button"]'
                )).filter(el => /research\\s+complete(?:d)?\\s*[\\s·•—\\-]/i.test(el.textContent || ''));
                if (textHits.length > 0) cards = textHits;
            }}
            if (!cards.length) {{
                const fallback = document.querySelectorAll(
                    '.font-claude-message button[class*="block"], ' +
                    '.font-claude-message [class*="artifact"]'
                );
                cards = Array.from(fallback);
            }}
            if (cards.length > idx) {{ cards[idx].click(); return true; }}
            return false;
        }}""", index)
    except Exception as e:
        log(f"Artifact click failed: {e}", "WARN")
        return False


async def _read_claude_artifact_panel(page):
    """Read content from the currently open artifact panel (right side)."""
    try:
        return await page.evaluate("""() => {
            const panelSelectors = [
                '[data-testid="artifact-content"]',
                '.artifact-content',
                '.artifact-panel .contents',
                'aside .prose', 'aside .markdown',
                '[class*="artifact-panel"] [class*="content"]',
                // Claude often renders artifact in a right-side panel with these
                '[class*="artifact"] .ProseMirror',
                '[class*="artifact"] [class*="rendered"]',
            ];
            for (const sel of panelSelectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText.length > 50) return el.innerText;
            }
            // Broader fallback: any right-side panel with substantial content
            const aside = document.querySelector('aside, [class*="side-panel"], [class*="right-panel"]');
            if (aside && aside.innerText.length > 200) return aside.innerText;
            return '';
        }""")
    except Exception as e:
        log(f"Artifact panel read failed: {e}", "WARN")
        return ""


async def _close_claude_artifact_panel(page):
    """Close the artifact panel by pressing Escape or clicking close."""
    try:
        # Try Escape first (most reliable)
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.3)
        # Verify panel closed by checking if aside/panel shrank
        still_open = await page.evaluate("""() => {
            const panel = document.querySelector('aside, [class*="artifact-panel"], [class*="side-panel"]');
            return panel && panel.offsetWidth > 100;
        }""")
        if still_open:
            # Try clicking close button
            await page.evaluate("""() => {
                const close = document.querySelector(
                    'aside button[aria-label="Close"], ' +
                    '[class*="artifact-panel"] button[aria-label="Close"], ' +
                    'aside button:has(svg[class*="close"]), ' +
                    'button[data-testid="close-artifact"]'
                );
                if (close) close.click();
            }""")
    except Exception:
        pass


async def scrape_claude_artifact_tracking(page, browser=None, cua_client=None,
                                          verbose=False, keep_open=False,
                                          already_open=False):
    """Scrape Claude's FIRST artifact for tracking/progress data during active research.
    DOM-first with CUA fallback. Returns enriched progress dict or None.
    keep_open=True: don't close the panel after read (re-used across polls).
    already_open=True: skip the click step (panel already open from prior poll)."""
    artifact_count = await _count_claude_artifacts(page)
    if artifact_count == 0:
        return None

    content = ""
    walker = {"steps": [], "sections": [], "source_urls": []}

    # Layer 1: DOM probe — open panel (if not already), read panel + DOM walker
    try:
        if not already_open:
            clicked = await _click_claude_artifact(page, index=0)
            if clicked:
                await asyncio.sleep(1.5)  # Wait for panel to render
        content = await _read_claude_artifact_panel(page)
        # Structured DOM walker — cheaper + more accurate than regex on plain text.
        # Reads the live artifact's checklist headings + section list + URL anchors
        # so steps[]/sections[]/source_urls[] reflect Claude's running outline.
        try:
            walker = await page.evaluate("""() => {
                const out = { steps: [], sections: [], source_urls: [] };
                const root = document.querySelector(
                    '[data-testid="artifact-content"], aside, [class*="artifact-panel"]'
                ) || document;
                root.querySelectorAll(
                    'li, [role="listitem"], [class*="step"], [class*="checklist"] > div, ' +
                    '[class*="task"] > div, [class*="activity"]'
                ).forEach(e => {
                    const t = (e.innerText || '').trim();
                    if (t && t.length > 4 && t.length < 240) out.steps.push(t.slice(0, 220));
                });
                root.querySelectorAll('h1, h2, h3').forEach(h => {
                    const t = (h.innerText || '').trim();
                    if (t && t.length > 1 && t.length < 120) out.sections.push(t);
                });
                const seen = new Set();
                root.querySelectorAll('a[href^="http"]').forEach(a => {
                    const h = a.href || '';
                    if (h && h.length < 500 && !h.includes('claude.ai') &&
                        !h.includes('anthropic.com') && !seen.has(h)) {
                        seen.add(h); out.source_urls.push(h);
                    }
                });
                out.steps = out.steps.slice(-15);
                out.sections = out.sections.slice(0, 20);
                out.source_urls = out.source_urls.slice(0, 50);
                return out;
            }""")
        except Exception as _we:
            log(f"[Claude] artifact DOM walker skipped: {_we}", "DEBUG")
        if not keep_open:
            await _close_claude_artifact_panel(page)
    except Exception as e:
        log(f"[Claude] Artifact DOM tracking failed: {e}", "WARN")

    # Layer 2: CUA fallback if DOM yielded nothing
    if not content and not walker.get("source_urls") and browser and cua_client:
        try:
            result = await agent_loop(cua_client, browser,
                PROMPT_SCRAPE_CLAUDE_ARTIFACT_TRACKING,
                "Open the first artifact in the conversation and read its content. "
                "Report URLs, steps, sections, and sources found. Then close the artifact panel.",
                model=CUA_MODEL, max_iterations=6, verbose=verbose)
            content = result.get("text", "")
        except Exception as e:
            log(f"[Claude] Artifact CUA tracking failed: {e}", "WARN")

    # Lowered gate: 5 chars (was 30) — accept partials. Walker URLs alone count.
    if (not content or len(content) < 5) and not walker.get("source_urls"):
        return None

    # Prefer DOM-walker output; fall back to regex on plain text only when walker empty.
    urls = walker["source_urls"] or list(dict.fromkeys(re.findall(r'https?://[^\s)>\]"]+', content or "")))[:30]
    steps = walker["steps"] or re.findall(r'(?:^|\n)\s*(?:\d+[\.\)]\s*|[-•]\s+)(.{10,200})', content or "")
    sections = walker["sections"] or re.findall(r'(?:^|\n)#{1,3}\s+(.{3,80})', content or "")
    if not sections:
        sections = re.findall(r'(?:^|\n)([A-Z][A-Z\s&]{5,60})(?:\n|$)', content or "")

    domains = set()
    for u in urls:
        try:
            from urllib.parse import urlparse
            domains.add(urlparse(u).netloc)
        except Exception:
            pass

    return {
        "status": "generating",
        "phase": "researching",
        "progress": (steps[-1] if steps else f"Tracking {len(urls)} sources from artifact"),
        "sources": max(len(domains), len(urls)),
        "source_urls": urls[:30],
        "sections": sections[:15],
        "steps": steps[:15],
        "tool_uses": [f"Analyzing: {s[:80]}" for s in sections[:5]],
        "partial_text_len": len(content or ""),
        "artifact_tracking": True,
        "artifact_count": artifact_count,
    }


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
        # Kill only orphaned Playwright Chrome from OUR profile directory.
        # NEVER kill all chrome.exe — that nukes the user's personal browser.
        try:
            import psutil
            our_profile = str(Path(self.profile_dir).resolve()).lower().replace("\\", "/")
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    if proc.info["name"] and "chrome" in proc.info["name"].lower():
                        cmdline = " ".join(proc.info["cmdline"] or []).lower().replace("\\", "/")
                        if our_profile in cmdline:
                            log(f"Killing orphaned Chrome PID {proc.info['pid']} (our profile)")
                            proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            await asyncio.sleep(1)
        except ImportError:
            pass
        except Exception:
            pass

        # Remove stale Chrome lock files from unclean shutdown — these prevent
        # Playwright from reusing the persistent profile directory.
        profile_path = Path(self.profile_dir)
        for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            lock_file = profile_path / lock_name
            if lock_file.exists():
                try:
                    lock_file.unlink()
                    log(f"Removed stale Chrome lock: {lock_name}")
                except Exception:
                    pass

        # Clean version-specific cache dirs that cause downgrade errors when
        # switching between system Chrome and Playwright's bundled Chromium.
        # These are regeneratable caches — login sessions live in Default/.
        import shutil
        for cache_dir in ("ShaderCache", "GrShaderCache", "GraphiteDawnCache",
                          "component_crx_cache", "extensions_crx_cache",
                          "BrowserMetrics", "Crashpad"):
            p = profile_path / cache_dir
            if p.is_dir():
                try:
                    shutil.rmtree(p, ignore_errors=True)
                except Exception:
                    pass
        # Also remove the downgrade sentinel that triggers cleanup attempts
        for sentinel in profile_path.glob("*.CHROME_DELETE"):
            try:
                shutil.rmtree(sentinel, ignore_errors=True)
            except Exception:
                pass

        # STEALTH-2026-04-19: Escalated from playwright + UA/UACH spoof to
        # patchright + real Chrome binary. Prior stack (playwright's bundled
        # Chromium, manual UA/UACH overrides, --disable-blink-features, init
        # scripts) still got blocked by ChatGPT and Claude login — bot-score
        # too high even with all the shims. patchright is a drop-in async
        # replacement that patches the deeper CDP / runtime.enable / chrome
        # object / headless-mode detection vectors internally, and pairs
        # with channel="chrome" to run the user's installed Chrome binary
        # instead of the bundled Chromium.
        #
        # channel="chrome" was previously avoided because we feared the
        # Windows singleton broker would delegate to the user's personal
        # Chrome and exit. That only happens when sharing a user-data-dir;
        # we now use a DEDICATED profile at ~/.super-research/browser-profile
        # so Chrome launches a separate process independent of the user's
        # daily browsing instance.
        #
        # Per patchright docs, we MUST NOT set user_agent, extra_http_headers,
        # or automation-disabling args — patchright handles those internally,
        # and adding them back produces inconsistencies that detection
        # scripts flag. Keep the init_script below as a belt-and-suspenders
        # layer; it's additive and patchright tolerates it.
        from patchright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            channel="chrome",
            headless=self.headless,
            viewport={"width": API_WIDTH, "height": API_HEIGHT},
            no_viewport=False,
        )
        # patchright owns the stealth layer from here. The prior hand-rolled
        # add_init_script (webdriver/plugins/languages/vendor/platform/
        # hardwareConcurrency/deviceMemory/chrome.runtime/permissions/WebGL)
        # ran AFTER patchright's own patches and overwrote them with values
        # that don't match what real Chrome actually exposes, producing
        # fingerprints worse than either layer alone. Keep the file-chooser
        # wiring; that's unrelated to stealth.
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()
        self.context.on("page", self._attach_file_handler)
        self._attach_file_handler(self.page)
        log("Browser started (stealth: patchright + channel=chrome)")

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
            # Kill only OUR profile's chromium — never nuke all chrome.exe
            try:
                import psutil
                our_profile = str(Path(self.profile_dir).resolve()).lower().replace("\\", "/")
                for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                    try:
                        if proc.info["name"] and "chrom" in proc.info["name"].lower():
                            cmdline = " ".join(proc.info["cmdline"] or []).lower().replace("\\", "/")
                            if our_profile in cmdline:
                                proc.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
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
                     phase=None, agent_name=None, target_page=None):
    """CUA agent loop — proven from original research.py.

    target_page (optional): Playwright Page reference. When provided, every
    screenshot re-anchors to this tab via bring_to_front. Prevents the
    "Claude polls screenshotted Gemini's tab" race when another async path
    swaps browser.page between iterations.
    """
    async def _anchored_screenshot():
        if target_page is not None:
            try:
                await browser.switch_to_page(target_page)
            except Exception:
                pass
        return await browser.screenshot()

    initial_ss = await _anchored_screenshot()
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
            # Resolve which phase/agent this CUA call is serving so the
            # frontend can route the warning to the correct per-agent
            # badge inside Phase 2 instead of collapsing into a phase-wide
            # banner. Fall back to _runtime.phase when caller omitted it.
            _phase = phase if phase is not None else _runtime.phase
            _agent = agent_name or None
            low = err.lower()
            if "rate_limit" in low or "429" in err:
                log("Rate limited — waiting 30s", "WARN")
                try:
                    emit_event("pipeline_warning", phase=_phase, agent=_agent,
                               message="Anthropic API rate-limited — retrying in 30s…",
                               details="Claude API returned HTTP 429 for a CUA call. Backing off automatically.",
                               alertType="retrying")
                except Exception:
                    pass
                await asyncio.sleep(30); continue
            elif "overloaded" in low or "529" in err:
                log("API overloaded — waiting 60s", "WARN")
                try:
                    emit_event("pipeline_warning", phase=_phase, agent=_agent,
                               message="Anthropic API overloaded — retrying in 60s…",
                               details="Claude API returned HTTP 529 for a CUA call. Backing off automatically.",
                               alertType="retrying")
                except Exception:
                    pass
                await asyncio.sleep(60); continue
            elif "workspace api usage limits" in low or ("400" in err and "usage limit" in low):
                # Non-recoverable: workspace cap is hit, retrying won't help
                # until the cap is raised in the Anthropic Console or the
                # reset date passes. Surface as a pipeline_error with an
                # actionable reason and bail out of the loop — callers can
                # decide whether to fall back or fail the phase.
                log(f"Workspace API cap hit — aborting CUA loop: {err[:200]}", "ERROR")
                # Phase 2 NEEDS CUA for polling — no fallback possible, so
                # the only honest option is to end the research. Other phases
                # (0/5) can still skip CUA gracefully.
                try:
                    if _phase == 2:
                        emit_event("pipeline_error", phase=_phase, agent=_agent,
                                   error="claude_api_cap",
                                   reason="Claude API hit the workspace usage cap. Phase 2 cannot run without CUA — raise the cap in the Anthropic Console or end the research.",
                                   details=err[:200],
                                   actions=[
                                       {"id": "stop", "label": "End research", "style": "danger",
                                        "command": {"action": "stop"}},
                                   ])
                    else:
                        emit_event("pipeline_error", phase=_phase, agent=_agent,
                                   error="claude_api_cap",
                                   reason="Claude API hit the workspace usage cap. Raise it in the Anthropic Console or wait until the reset date, then retry.",
                                   details=err[:200],
                                   actions=[
                                       {"id": "retry", "label": "Retry", "style": "primary",
                                        "command": {"action": "retry_phase", "phase": _phase}},
                                       {"id": "skip", "label": "Skip", "style": "default",
                                        "command": {"action": "skip_phase", "phase": _phase}},
                                   ])
                except Exception:
                    pass
                return {"status": "error", "text": str(e)}
            elif "401" in err and ("unauthorized" in low or "invalid" in low or "api_key" in low):
                log(f"Claude API key rejected — aborting CUA loop: {err[:200]}", "ERROR")
                try:
                    emit_event("pipeline_error", phase=_phase, agent=_agent,
                               error="claude_api_unauthorized",
                               reason="Claude API key was rejected. Update CUA_API_KEY and restart the backend.",
                               details=err[:200])
                except Exception:
                    pass
                return {"status": "error", "text": str(e)}
            else:
                log(f"API error: {e}", "ERROR")
                try:
                    emit_event("pipeline_warning", phase=_phase, agent=_agent,
                               message="Anthropic API error — CUA call failed",
                               details=f"{err[:200]}",
                               alertType="error")
                except Exception:
                    pass
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
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": await _anchored_screenshot()}},
                ]})
                recent_actions.clear()
                continue

            if act == "screenshot":
                ss = await _anchored_screenshot()
                tool_results.append({"type": "tool_result", "tool_use_id": tb.id,
                    "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ss}}]})
            else:
                ss = await execute_action(browser, act, tb.input)
                # Re-anchor after action — execute_action may have navigated,
                # opened a new tab, or the OS swapped focus during the click.
                if target_page is not None:
                    try:
                        await browser.switch_to_page(target_page)
                    except Exception:
                        pass
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
    Scrolls both page body AND chat container — DR stop button is in chat UI, not input area.

    2026-04 iframe fix: ChatGPT Deep Research renders inside a cross-origin
    sandbox iframe (connector_openai_deep_research.web-sandbox.oaiusercontent.com).
    Host-page selectors miss the DR stop button + progress entirely, so we
    walk `page.frames` and check inside the DR iframe for any "researching"/
    "sources"/"stop" signal. Matches the detect_completion_chatgpt pattern."""
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
        host_hit = await page.evaluate("""() => {
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
            // Body-level DR keyword sweep — narrowed to present-progressive
            // phrases that don't survive the finished response. Removed
            // 'deep research' (the model badge persists), 'sources found'
            // (appears in finished summary), 'researching' (could be in any
            // narrative). Kept the unambiguous in-progress phrases.
            const bl = (document.body?.innerText || '').toLowerCase();
            // Strong done signal: "Thought for X seconds" badge renders only
            // AFTER the thinking phase completes. With no Stop button found
            // above, its presence means the response is fully settled.
            if (bl.includes('thought for ')) return false;
            const hostKws = ['sources and counting', 'searching the web', 'reading sources'];
            if (hostKws.some(k => bl.includes(k))) return true;
            return !!document.querySelector('.result-streaming, [data-is-streaming="true"]');
        }""")
        if host_hit:
            return True

        # ── DR iframe walk ──
        # Deep Research renders inside cross-origin oaiusercontent sandbox.
        # Walk frames, look for deep_research/oaiusercontent URL match, then
        # check for stop button / active keywords / partial content inside.
        try:
            for frame in page.frames:
                try:
                    src = (frame.url or "").lower()
                except Exception:
                    continue
                if not src:
                    continue
                if ("deep_research" in src or "oaiusercontent" in src):
                    try:
                        active = await frame.evaluate("""() => {
                            // Any stop button
                            for (const b of document.querySelectorAll('button')) {
                                const t = (b.textContent || '').trim().toLowerCase();
                                const al = (b.getAttribute('aria-label') || '').toLowerCase();
                                if (t === 'stop' || t === 'stop research' ||
                                    al.includes('stop')) return true;
                            }
                            // Spinner / progress
                            if (document.querySelector(
                                '[role="progressbar"], [class*="progress"], [class*="spinner"], ' +
                                '[class*="loading"], [data-is-streaming="true"]'
                            )) return true;
                            const bl = (document.body?.innerText || '').toLowerCase();
                            // Strong done signal: "Thought for X seconds" badge
                            // renders only AFTER thinking completes. With no Stop
                            // button or spinner detected above, its presence means
                            // the response is settled — treat as definitively done.
                            if (bl.includes('thought for ')) return false;
                            // Removed keyword fallthrough entirely. Inside the DR
                            // iframe, body text IS the rendered brief itself —
                            // the brief can legitimately contain phrases like
                            // "after reading sources" or "searching the web", and
                            // any keyword match would re-introduce the same
                            // false-positive class as the deleted length>200
                            // fallback. Visual markers above (stop button,
                            // progressbar/spinner/streaming) are reliable signals
                            // for "still active" inside the iframe; keywords add
                            // risk without unique coverage.
                            return false;
                        }""")
                        if active:
                            return True
                    except Exception:
                        pass
                    break
        except Exception:
            pass
        return False
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


# ── MutationObserver streaming (real-time partial text per agent page) ───
#
# We inject a throttled MutationObserver into each agent page that watches
# the assistant's response container. It fires `window.onStream({len,text})`
# every ~500ms while the response grows. The callback here updates a shared
# dict keyed by page id, so the poll loop (Phase 1 or Phase 2) can read the
# latest `observer_text_len` + `observer_preview` when it emits agent_progress.
#
# This gives the frontend true token-level streaming while the 30s DOM poll
# keeps structured fields (sources/sections/steps) fresh. No polling wasted
# on just-a-few-more-chars-every-second — the observer handles that slice.

_OBSERVER_SELECTORS = {
    "chatgpt": ['[data-message-author-role="assistant"]:last-of-type',
                'main [data-message-id]:last-of-type',
                'article.text-token-text-primary:last-of-type'],
    "gemini":  ['message-content:last-of-type',
                '.model-response-text:last-of-type',
                '.response-container:last-of-type'],
    "claude":  ['[data-testid="assistant-message"]:last-of-type',
                '.font-claude-message:last-of-type',
                '[data-is-streaming]:last-of-type'],
}

# Keyed by id(page) — each page gets its own stream state
_agent_streams: dict[int, dict] = {}


def _make_stream_callback(page_id: int):
    """Return a callback for page.expose_function('onStream', ...)"""
    def cb(data):
        try:
            st = _agent_streams.setdefault(page_id, {})
            st["observer_text_len"] = int(data.get("len", 0) or 0)
            st["observer_preview"] = str(data.get("text", "") or "")[:500]
            st["last_update"] = time.time()
        except Exception:
            pass
    return cb


async def inject_agent_observer(page, agent_key: str):
    """Inject a throttled MutationObserver on `page` that streams the assistant
    response's partial text length + last 500 chars to Python.

    Idempotent: re-call after navigations to re-attach. The exposed function
    `onStream` is registered once per page (Playwright will raise on
    re-expose — we catch that).
    """
    page_id = id(page)
    _agent_streams.setdefault(page_id, {
        "observer_text_len": 0, "observer_preview": "", "last_update": 0.0,
    })
    try:
        await page.expose_function("onStream", _make_stream_callback(page_id))
    except Exception:
        # Already exposed — safe to ignore, callback is already bound
        pass

    selectors = _OBSERVER_SELECTORS.get(agent_key, [])
    if not selectors:
        return False

    script = """
    (selectors) => {
        if (window.__agentObserver) {
            try { window.__agentObserver.disconnect(); } catch(e) {}
        }
        let container = null;
        for (const sel of selectors) {
            try { container = document.querySelector(sel); } catch(e) {}
            if (container) break;
        }
        if (!container) {
            window.__agentObserverActive = false;
            return false;
        }
        let lastLen = 0;
        let timer = null;
        const mo = new MutationObserver(() => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                const text = container.innerText || '';
                if (text.length === lastLen) return;
                lastLen = text.length;
                try {
                    window.onStream({ text: text.slice(-500), len: text.length, ts: Date.now() });
                } catch(e) {}
            }, 500);
        });
        mo.observe(container, {childList: true, subtree: true, characterData: true});
        window.__agentObserver = mo;
        window.__agentObserverActive = true;
        return true;
    }
    """
    try:
        ok = await page.evaluate(script, selectors)
        return bool(ok)
    except Exception as e:
        log(f"[observer-{agent_key}] inject failed: {e}", "WARN")
        return False


def get_observer_state(page) -> dict:
    """Read the latest MutationObserver snapshot for this page.
    Returns {} if observer hasn't been injected or hasn't fired yet."""
    try:
        return _agent_streams.get(id(page), {}) or {}
    except Exception:
        return {}


async def poll_until_done(page, verify_fn, label, poll_interval, max_wait_min,
                          browser=None, cua_client=None, verbose=False, phase=2):
    """Poll page until response is complete. Smart: uses CUA to check if DOM selectors fail."""
    wait_start = time.time()
    max_wait = max_wait_min * 60
    paused_total = 0.0  # accumulator: time spent in wait_if_paused (pause-aware)
    consecutive_not_generating = 0
    cua_checked = False
    last_heartbeat = time.time()
    # ── ChatGPT activity-strip open state (P1 only — Phase1 / Phase1-followup) ──
    # Mirrors the per-agent dict P2 round-robin uses, scoped to this single
    # poll call. Flips _panel_open_done True on first verified open. DOM
    # misses count both "found:false" AND "clicked but verify:false". CUA
    # tier-3 capped at 1/call. The same robust helper (research.py:5048)
    # works regardless of phase — Pro+ET in P1 produces the same React-
    # rendered styled <div> strip that DR in P2 does.
    _panel_open_done = False
    _panel_dom_misses = 0
    _panel_cua_attempts = 0
    _panel_poll_cycles = 0  # ticks once per ChatGPT P1 poll while panel still closed
    # Stall detector — multi-signal (2026-04-25 strictness rewrite):
    # tracks text + sources + steps. ChatGPT DR's "researching" phase
    # legitimately produces zero text growth for 5-15 min while sources
    # and steps accumulate, so a text-only stall detector false-fired
    # during normal in-progress work. Now stall fires only when ALL
    # THREE signals flatline for 20 min (was 10 min text-only) AND the
    # detector still says "generating" — a genuinely-done response is
    # caught earlier by the verify_fn=False completion path.
    last_seen_len = 0
    last_seen_sources = 0
    last_seen_steps_sig = 0
    stall_window_start = None  # time.time() when ALL signals stopped growing
    STALL_THRESHOLD_SEC = 1200  # 20 min of multi-signal flatness → likely stuck

    # Subtract paused_total from elapsed so a long user pause doesn't make
    # this inner timer falsely fire after resume. Without this, a user who
    # pauses for an hour during P1 would return to a poll loop that thinks
    # MAX_WAIT_PRO=45min has elapsed and aborts before checking if the brief
    # actually completed server-side. The outer active-time deadline
    # (_await_phase_with_active_deadline) is the ultimate safety net but
    # this inner check should also be pause-aware so it doesn't false-fire.
    while (time.time() - wait_start - paused_total) < max_wait:
        # ── Stop/Pause check ──
        if _controls.is_stop():
            log(f"[{label}] STOP requested — aborting poll")
            return False
        if _controls.is_pause():
            emit_event("pipeline_paused", phase=phase)
            _pause_t0 = time.monotonic()
            await _controls.wait_if_paused()
            _this_pause = time.monotonic() - _pause_t0
            paused_total += _this_pause
            # Don't count user pause time toward stall — push the stall
            # window forward so a long pause doesn't false-fire on the
            # next post-resume tick.
            if stall_window_start is not None:
                stall_window_start += _this_pause
            if _controls.is_stop():
                log(f"[{label}] STOP after pause — aborting poll")
                return False
            # Pause+input+resume = rerun the phase from the start. Bail out so
            # the orchestrator can detect `_runtime.restart_requested` and loop.
            if _controls.peek_extra_context():
                _runtime.restart_requested = True
                log(f"[{label}] Extra context during pause — signalling phase restart")
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
                # Hoisted from dedupe block — needed by panel-open gate below.
                elapsed_sec = int(time.time() - wait_start)

                # ── ChatGPT activity-strip open (P1 mirror of P2 round-robin) ──
                # Pro+ET sometimes does mid-thinking web searches → "Looking
                # into X… N searches" strip at bottom of chat. Same robust
                # DOM helper (walks * + dispatches full event chain — v1
                # narrow selector matched 0 candidates because the strip is
                # a styled <div>). Gate: 180s wall-clock. After 2 DOM misses
                # → CUA tier-3 (capped 1/call). Only fires for ChatGPT P1
                # entry points; Gemini/Claude have own paths.
                if label in ("Phase1", "Phase1-followup") and not _panel_open_done:
                    _panel_poll_cycles += 1
                if (label in ("Phase1", "Phase1-followup")
                        and (_panel_poll_cycles >= 2 or elapsed_sec >= 60)
                        and not _panel_open_done):
                    try:
                        res = await _open_chatgpt_activity_panel(page)
                        cands = (res or {}).get("candidates", 0)
                        if not res or not res.get("found"):
                            _panel_dom_misses += 1
                            log(f"[{label}] panel DOM miss #{_panel_dom_misses} "
                                f"(elapsed={elapsed_sec}s, walked_hits={cands}) — "
                                f"strip not yet rendered or wording changed", "DEBUG")
                        elif res.get("alreadyExpanded"):
                            _panel_open_done = True
                            log(f"[{label}] activity panel already expanded at "
                                f"elapsed={elapsed_sec}s — label: \"{res.get('label','')[:80]}\"")
                        elif res.get("clicked"):
                            await asyncio.sleep(2.0)
                            verified = await _verify_chatgpt_panel_open(page)
                            if verified:
                                _panel_open_done = True
                                log(f"[{label}] activity panel opened via DOM at "
                                    f"elapsed={elapsed_sec}s — clickedTag={res.get('clickedTag','?')}")
                            else:
                                _panel_dom_misses += 1
                                log(f"[{label}] DOM clicked but panel didn't render — "
                                    f"miss #{_panel_dom_misses}", "WARN")
                        else:
                            _panel_dom_misses += 1
                            log(f"[{label}] panel found but click failed — "
                                f"err={res.get('error','?')}", "WARN")
                    except Exception as _pe:
                        log(f"[{label}] activity panel open failed: {_pe}", "WARN")
                        _panel_dom_misses += 1

                    # CUA tier-3 escalation after 2 DOM misses (capped at 1/call).
                    if (not _panel_open_done
                            and _panel_dom_misses >= 2
                            and _panel_cua_attempts == 0
                            and cua_client and browser):
                        log(f"[{label}] DOM missed strip 2x — escalating to CUA tier-3 "
                            f"(elapsed={elapsed_sec}s)")
                        try:
                            emit_event("tier_transition", phase=phase, agent="chatgpt",
                                       op="open_activity_panel_p1", from_tier="dom",
                                       to_tier="cua", reason="dom_2_misses")
                        except Exception:
                            pass
                        _panel_cua_attempts = 1
                        async def _cgpt_p1_cua():
                            return await asyncio.wait_for(
                                agent_loop(cua_client, browser,
                                    PROMPT_OPEN_CHATGPT_SOURCE_PANEL,
                                    "Open the activity strip at the bottom of this ChatGPT "
                                    "Pro/Thinking conversation. ONE click only. Verify the "
                                    "side panel slides out before reporting.",
                                    model=CUA_MODEL, max_iterations=5,
                                    verbose=verbose, target_page=page),
                                timeout=120.0)
                        try:
                            cua_res = await _shadow_observed_cua(
                                page, hotspot_id="7c-p1", phase=phase, platform="chatgpt",
                                current_step="open_activity_panel_p1",
                                context_hint=f"P1 brief poll DOM 2-miss at elapsed={elapsed_sec}s",
                                expected_outcome="side panel mounts on right with step list",
                                cua_coro_factory=_cgpt_p1_cua)
                            out = ((cua_res or {}).get("text") or "").lower()
                            if "panel: open" in out or "panel: already_open" in out:
                                _panel_open_done = True
                                log(f"[{label}] activity panel opened via CUA tier-3")
                            else:
                                log(f"[{label}] CUA tier-3 didn't confirm panel: {out[:120]}", "WARN")
                        except asyncio.TimeoutError:
                            log(f"[{label}] CUA tier-3 timed out after 120s", "WARN")
                        except Exception as _ce:
                            log(f"[{label}] CUA tier-3 failed: {_ce}", "WARN")

                # Enrich with MutationObserver data (token-level stream)
                _obs = get_observer_state(page)
                _obs_len = _obs.get("observer_text_len", 0) or 0
                _obs_preview = _obs.get("observer_preview", "") or ""
                # partialTextLen is max of DOM scrape + observer (observer is usually fresher)
                _merged_partial_len = max(progress.get("partial_text_len", 0) or 0, _obs_len)
                # Multi-signal stall tracking (2026-04-25): stamp time when
                # ALL signals stop growing; reset on any growth in any
                # signal. ChatGPT DR's researching phase produces no text
                # growth but sources and steps continue — text-only stall
                # detection false-fired during legit in-progress work.
                _p1_sources = int(progress.get("sources", 0) or 0)
                _p1_steps_sig = len(progress.get("steps", []) or [])
                _grew = (_merged_partial_len > last_seen_len
                         or _p1_sources > last_seen_sources
                         or _p1_steps_sig > last_seen_steps_sig)
                if _grew:
                    last_seen_len = max(last_seen_len, _merged_partial_len)
                    last_seen_sources = max(last_seen_sources, _p1_sources)
                    last_seen_steps_sig = max(last_seen_steps_sig, _p1_steps_sig)
                    stall_window_start = None
                elif (_merged_partial_len > 0 or _p1_sources > 0) and stall_window_start is None:
                    stall_window_start = time.time()
                # Deduplicate: emit if data changed OR every 30s (elapsed_bucket).
                # Without elapsed_bucket, P1's Extended Thinking window (5-15 min
                # of zero text/source growth) would suppress every emit for the
                # whole window, leaving the FE stuck on "Opening ChatGPT…". The
                # 30s tick guarantees the dropdown narration stays alive — same
                # pattern P2's round-robin polling uses.
                # elapsed_sec hoisted to top of try block for panel-open gate.
                progress_key = json.dumps({
                    "status": progress.get("status", ""),
                    "sources": progress.get("sources", 0),
                    "partialTextLen": _merged_partial_len,
                    "sections_len": len(progress.get("sections", [])),
                    "steps_len": len(progress.get("steps", []) or []),
                    # Coarse-bucket the observer length so small bumps don't spam Firestore
                    "obs_bucket": _merged_partial_len // 200,
                    # 30s tick keeps narration live during long ET windows
                    "elapsed_bucket": elapsed_sec // 30,
                }, sort_keys=True)
                if _last_progress.get(label) != progress_key:
                    _last_progress[label] = progress_key
                    expected_min = get_expected_minutes(phase)
                    # Loosen ET gate: P1 brief mode (Pro + Extended Thinking, NOT
                    # Deep Research) returns status="idle" pre-stream because
                    # scrape_progress_chatgpt has no DR signals + zero tokens.
                    # We're inside poll_until_done so by definition the agent
                    # IS working — show "Extended Thinking active" rather than
                    # the stale pre-poll string ("Opening ChatGPT…").
                    is_et = (progress.get("status") in ("generating", "idle")
                             and progress.get("sources", 0) == 0
                             and _merged_partial_len < 500)
                    if is_et:
                        # Agent-specific label: ChatGPT kept "Extended Thinking",
                        # Claude renamed to "Adaptive Thinking", Gemini uses
                        # "Planning" (pre-research planning step). Emitting the
                        # wrong label on Claude misleads users into thinking a
                        # deprecated setting is on.
                        _nk = normalize_agent_key(label)
                        _think_label = (
                            "Adaptive Thinking" if _nk == "claude" else
                            "Planning" if _nk == "gemini" else
                            "Extended Thinking"
                        )
                        progress["status"] = "extended_thinking"
                        # Drop elapsed/typical from the progress string —
                        # the FE phase header already renders both from
                        # elapsedSec + expectedMinutes (top of dropdown),
                        # and duplicating them in the per-platform card was
                        # confusing + stale-looking when the top counter
                        # advanced but the baked-in string didn't.
                        progress["progress"] = f"{_think_label} active"
                    agent_key = normalize_agent_key(label)
                    emit_event("agent_progress", phase=phase, agent=agent_key,
                        status=progress.get("status", ""),
                        progress=progress.get("progress", ""),
                        sources=progress.get("sources", 0),
                        sourceUrls=progress.get("source_urls", []),
                        sections=progress.get("sections", []),
                        partialTextLen=_merged_partial_len,
                        partialTextPreview=_obs_preview,
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

            # First "not generating" could be a DOM selector issue or a
            # split-second between tokens. Drop to 2-consecutive (was 3)
            # — saves 30s of slack per phase. The DOM selectors are tight
            # post-2026-04 overhaul; false-positive risk is low. CUA is
            # still the visual fallback after 2 consecutive.
            if consecutive_not_generating <= 1:
                await asyncio.sleep(5)
                continue

            # After 2 consecutive "not generating" — warn user + ask CUA to verify
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
                # CRITICAL: A structural CUA failure (workspace cap, 401, 529,
                # etc.) returns {"status": "error", "text": str(exception)}.
                # Previously that error text fell through the heuristic parse
                # below and hit the "assume complete" default, silently
                # advancing the phase on a dead CUA call. Now: skip CUA this
                # tick, trust the DOM check on the next poll. The underlying
                # Anthropic error has already been surfaced to the frontend
                # via pipeline_error by agent_loop's own error handler.
                if diag.get("status") == "error":
                    log(f"[{label}] CUA diagnostic unavailable ({(diag.get('text') or '')[:80]}) — "
                        f"falling back to DOM for this poll tick", "WARN")
                    cua_checked = False
                    await asyncio.sleep(poll_interval)
                    continue
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
            # Stall surface: detector still says "running" but ALL three
            # signals (text + sources + steps) stopped growing for
            # STALL_THRESHOLD_SEC. Catches the "ChatGPT alive but frozen
            # mid-stream" case proactively — raises into the phase retry-
            # loop's `except asyncio.TimeoutError:` so the user gets the
            # [Retry, Skip] alert. Multi-signal makes false alarms
            # vanishingly rare: ChatGPT DR's researching phase always
            # grows sources/steps even when text doesn't.
            if (stall_window_start is not None
                    and (time.time() - stall_window_start) > STALL_THRESHOLD_SEC):
                _stall = int(time.time() - stall_window_start)
                log(f"[{label}] Stall detected: text={last_seen_len}, "
                    f"sources={last_seen_sources}, steps={last_seen_steps_sig} — "
                    f"all flat for {_stall}s while detector says generating "
                    f"→ surfacing for user decision (Retry/Skip)", "WARN")
                raise asyncio.TimeoutError(
                    f"phase {phase} response stalled "
                    f"(text={last_seen_len}, sources={last_seen_sources}, "
                    f"steps={last_seen_steps_sig}; flat for {_stall}s)"
                )

        elapsed_min = int(time.time() - wait_start) // 60
        log(f"[{label}] Still generating... ({elapsed_min}m elapsed)")
        await asyncio.sleep(poll_interval)

    log(f"[{label}] Timeout ({max_wait_min}min)", "WARN")
    return False


# ── Round-Robin Polling (Phase 2) ─────────────────────────────────────────────

async def _restart_phase2_agent(name: str, browser, cua_client, brief_text: str,
                                 brief_path, verbose: bool):
    """Hard-retry helper: re-run the per-agent setup for a Phase 2 agent from
    scratch (fresh tab, Pro/DR mode selection, brief paste, submit, verify).

    Mirrors the per-agent setup blocks inside `run_phase2` — kept in sync
    manually because run_phase2's setup is entangled with agent startup
    ordering (Gemini waits for Start-research button AFTER ChatGPT/Claude
    submit). For a single-agent restart, ordering doesn't matter: run the
    agent's own setup in isolation.

    Returns `(new_page, verified_bool)` or `None` on hard failure (including
    paste/setup failure where start_agent_no_gemini_wait returned ok=False)."""
    if name == "ChatGPT":
        new_page, _setup_ok = await start_agent_no_gemini_wait(
            browser, cua_client, "https://chatgpt.com",
            PROMPT_CHATGPT_DEEP_RESEARCH,
            "Enable Deep Research mode in ChatGPT. Do NOT type — just set up and focus input. Say 'ready for paste'.",
            brief_text, "2A-retry", "ChatGPT", verbose, brief_path=brief_path)
        if not _setup_ok:
            return (new_page, False)
        verified = await wait_until_verified(
            verify_chatgpt_generating, new_page, "2A-retry",
            browser=browser, cua_client=cua_client,
            max_retries=15, interval=3, verbose=verbose)
        return (new_page, verified)

    if name == "Claude":
        new_page, _setup_ok = await start_agent_no_gemini_wait(
            browser, cua_client, "https://claude.ai/new",
            PROMPT_CLAUDE_DEEP_RESEARCH,
            "Select Opus 4.7 + Adaptive Thinking + Research tool. Do NOT type — just set up and focus input. Say 'ready for paste'.",
            brief_text, "2C-retry", "Claude", verbose, brief_path=brief_path)
        if not _setup_ok:
            return (new_page, False)
        verified = await wait_until_verified(
            verify_claude_generating, new_page, "2C-retry",
            browser=browser, cua_client=cua_client,
            max_retries=15, interval=3, verbose=verbose)
        return (new_page, verified)

    if name == "Gemini":
        new_page, _setup_ok = await start_agent_no_gemini_wait(
            browser, cua_client, "https://gemini.google.com",
            PROMPT_GEMINI_DEEP_RESEARCH,
            "Enable Deep Research mode in Gemini. Do NOT type — just set up and focus input. Say 'ready for paste'.",
            brief_text, "2B-retry", "Gemini", verbose, brief_path=brief_path)
        if not _setup_ok:
            return (new_page, False)
        await browser.switch_to_page(new_page)
        await asyncio.sleep(2)

        # Gemini needs an extra click: wait up to 90s for "Start research"
        # button, click via JS, fall back to CUA if JS can't find it.
        start_clicked = False
        for attempt in range(45):
            try:
                clicked = await new_page.evaluate("""() => {
                    const btns = document.querySelectorAll('button');
                    for (const b of btns) {
                        const txt = b.textContent.trim().toLowerCase();
                        if (txt.includes('start research')) { b.click(); return true; }
                    }
                    return false;
                }""")
                if clicked:
                    start_clicked = True
                    await asyncio.sleep(5)
                    break
            except Exception:
                pass
            await asyncio.sleep(2)
        if not start_clicked and cua_client:
            await browser.switch_to_page(new_page)
            fix = await agent_loop(cua_client, browser,
                PROMPT_GEMINI_START_RESEARCH,
                "Click the 'Start research' button to begin the deep research.",
                model=CUA_MODEL, max_iterations=10, verbose=verbose)
            if "click" in (fix.get("text") or "").lower():
                start_clicked = True
                await asyncio.sleep(5)

        verified = await wait_until_verified(
            verify_gemini_generating, new_page, "2B-retry",
            browser=browser, cua_client=cua_client,
            max_retries=15, interval=3, verbose=verbose)
        return (new_page, verified)

    return None


# ── Per-Agent Extract + Record (content-first, link-second) ──────────────────
# Called by poll_all_agents_round_robin the moment detect_completion_* flips
# True for an agent. Runs the locked 2026-04 emission ladder end-to-end so the
# frontend gets the MD, the public link (or chat-URL fallback), and the
# `complete` status all together — backend and frontend stay in sync, and the
# frontend tick mark appears at the same moment the backend marks completed_set.
#
# Emission order (user-locked):
#   1. agent_progress status=extracting          (before we touch anything)
#   2. extract content → save documents/<agent>.md + Firestore mirror
#   3. attempt public Share/Publish link (short-circuited for ChatGPT iframe)
#   4. emit link_extracted { url, verified, fallback? }
#      (public if verified, else chat-URL fallback with verified=False)
#   5. agent_progress status=complete
#   Caller then does completed_set.add(agent) and clears extraction_in_progress.

async def extract_and_record_agent(name, page, browser, cua_client, queue_dir,
                                    elapsed_sec=0, verbose=False):
    """Per-agent extract + save + emit ladder. Returns a result dict
    the caller drops into results[]. Never raises — on any internal failure
    returns status='failed' so the poll loop can decide whether to retry.

    2026-04-25: Markdown-as-primary architecture (mirrors P1).
    The moment markdown lands in Firestore, the function emits link_extracted
    (in-app /documents URL, primary=True, verified=True) + agent_progress
    complete. Share-link extraction is REMOVED from P2 entirely — Phase 5's
    Google Doc creation uses Phase 3's link extraction instead. The in-app
    /documents?open=… link is the only link FE renders in PhaseDropdown.

    Result dict semantics:
      url          — conversation URL (page.url) for downstream resume
      _in_app_url  — /documents?open=… for the FE primary link
      verified     — True if MD text > 0 (the in-app primary IS verified)
    """
    agent_key = name.lower().replace(" ", "")

    # Step 1 — Emit extracting so the frontend can show "Extracting…" spinner
    try:
        emit_event("agent_progress", phase=2, agent=agent_key,
                   status="extracting",
                   progress=f"Extracting {name} research content…")
    except Exception:
        pass

    # Pull the agent's tab to the foreground so extract_*_response can operate
    try:
        await browser.switch_to_page(page)
        await asyncio.sleep(1)
    except Exception as e:
        log(f"[{name}] switch_to_page failed: {e}", "WARN")

    # Step 2 — Content extraction (HTML→MD → copy button → JS → clipboard)
    extract_fn_map = {
        "ChatGPT": extract_chatgpt_response,
        "Gemini":  extract_gemini_response,
        "Claude":  extract_claude_response,
    }
    extract_fn = extract_fn_map.get(name)
    text = ""
    if extract_fn:
        try:
            # Claude: poll-loop kept artifact-1 panel open via scrape_claude_artifact_tracking
            # (commit d45807f). Pass that signal so the extractor closes-1 before clicking
            # the LAST card (which opens artifact-2, the final report). Without this hand-off,
            # the LAST-card click can no-op (artifact_count==1) or race the panel swap.
            extra_kw = {}
            if name == "Claude":
                extra_kw["artifact_panel_open"] = bool(getattr(_runtime, "claude_artifact_panel_open", False))
            text = await extract_fn(page, browser=browser, cua_client=cua_client,
                                     label=name, verbose=verbose, **extra_kw) or ""
        except Exception as e:
            log(f"[{name}] Content extraction error: {e}", "WARN")
            text = ""
        # Panel state mutated: extract_claude_response (when it ran) opened artifact-2,
        # so the polling-loop's "panel 1 is open" signal is no longer accurate. Clear
        # it so a subsequent retry/poke doesn't make scrape_claude_artifact_tracking
        # skip the click (already_open=True) and read artifact-2 into the running tracker.
        if name == "Claude":
            try:
                _runtime.claude_artifact_panel_open = False
            except Exception:
                pass
    n_chars = len(text)

    # Step 2b — Save MD to disk (Phase 3 input) + Firestore mirror (FE doc).
    # md_saved tracks the FIRESTORE write because that's what gates the FE's
    # `docReachable` accordion check. A successful local-only save is not
    # enough — without the subcollection write, the FE accordion would sit
    # in `isAgentSyncing` until the run ends. Retry once (transient quota /
    # network blips) before accepting the failure.
    local_saved = False
    md_saved = False
    md_content = ""
    if text and queue_dir:
        try:
            documents_dir = queue_dir / "documents"
            documents_dir.mkdir(parents=True, exist_ok=True)
            fname = agent_key + ".md"
            md_content = f"# {name} Deep Research\n\n{text}"
            (documents_dir / fname).write_text(md_content, encoding="utf-8")
            local_saved = True
            log(f"[{name}] Saved {n_chars} chars to documents/{fname}")
        except Exception as e:
            log(f"[{name}] Local MD save failed: {e}", "WARN")
        if local_saved:
            for _attempt in range(2):
                if save_document_to_firestore(agent_key, md_content, f"{name} Deep Research"):
                    md_saved = True
                    break
                if _attempt == 0:
                    log(f"[{name}] Firestore document sync attempt 1 failed — retrying in 2s", "WARN")
                    await asyncio.sleep(2.0)
                else:
                    log(f"[{name}] Firestore document sync FAILED after retry — agent will be marked failed "
                        f"(FE doc-reachable gate would never flip without the subcollection write).", "ERROR")

    # Conversation URL — captured NOW because the page may navigate during the
    # parallel share-link worker (Gemini's Share & Export modal can redirect).
    conversation_url = ""
    try:
        conversation_url = (page.url or "") if page else ""
    except Exception:
        conversation_url = ""

    # Step 3 — Markdown-as-primary emit (P1 mirror), STRICT gate.
    # The FE flips an agent to ✓ only when it sees:
    #   (a) link_extracted with primary=true + verified=true, AND
    #   (b) the doc reachable via useResearches (subcollection sync).
    # Therefore we must NOT emit `complete` unless both _fb_research_id (so the
    # in-app URL has an anchor) AND n_chars > 0 (so a doc actually exists in
    # Firestore for the FE to find). A bare /documents URL without anchor is
    # not enough — it would let the FE flip ✓ without a real target.
    has_anchor = bool(_fb_research_id)
    _in_app_url = (f"/documents?open={_fb_research_id}:{agent_key}"
                   if has_anchor else "/documents")
    _in_app_label = f"Read {name} report"
    if n_chars > 0 and has_anchor and md_saved:
        try:
            emit_event("link_extracted", phase=2, agent=agent_key,
                       url=_in_app_url, label=_in_app_label,
                       verified=True, primary=True)
        except Exception:
            pass
        try:
            emit_event("agent_progress", phase=2, agent=agent_key,
                       status="complete",
                       progress=f"Content extracted: {n_chars} chars ({elapsed_sec}s)",
                       partialTextLen=n_chars,
                       elapsedSec=int(elapsed_sec or 0),
                       links=[{"label": _in_app_label, "url": _in_app_url,
                               "verified": True, "primary": True}])
        except Exception:
            pass
    else:
        # No content extracted OR no anchor OR Firestore write failed — emit
        # failed (FE keeps spinner, never flips ✓ without a reachable doc).
        _why = ("0 chars" if n_chars <= 0
                else "no research anchor (_fb_research_id missing)" if not has_anchor
                else "Firestore document sync failed after retry — FE doc-reachable would never flip")
        try:
            emit_event("agent_progress", phase=2, agent=agent_key,
                       status="failed",
                       progress=f"Content extraction failed — {_why} ({elapsed_sec}s)",
                       partialTextLen=max(int(n_chars), 0),
                       elapsedSec=int(elapsed_sec or 0))
        except Exception:
            pass

    # ── Step 4 — Inline share-link extraction (Option A, 2026-04-25) ──
    # Best-effort, **NOT streamed to FE**. We call the extractor functions
    # directly (no extract_with_retry) so we don't emit `link_extracting` /
    # `link_extracted` / `link_extraction_failed` events into the FE event
    # stream. The FE already showed `link_extracted primary=true` for the
    # in-app /documents URL above; a second link_extracted for the share
    # URL would land as a non-primary record (filtered out by P1+P2 strict
    # rule) but would still bloat steps[] and dirty agentAlerts via the
    # usePipeline link_extracted handler. Direct call keeps the FE clean.
    #
    # 90 s outer budget per agent. Public success → kind="public",
    # verified=True. Public failure (timeout, error, unverified URL) →
    # conversation URL, kind="conversation", verified=False. The run
    # always advances; Phase 5 always has *some* URL.
    if n_chars > 0:
        share_extractor_map = {
            "ChatGPT": extract_share_link_chatgpt,
            "Gemini":  extract_share_link_gemini,
            "Claude":  extract_share_link_claude,
        }
        share_extractor = share_extractor_map.get(name)
        share_url = conversation_url
        share_kind = "conversation"
        share_verified = False
        share_label = f"{name} conversation"
        if share_extractor:
            _share_t0 = time.time()
            try:
                link_res = await asyncio.wait_for(
                    share_extractor(browser, cua_client=cua_client,
                                    label=f"{name} public share", verbose=verbose),
                    timeout=90.0,
                )
                _elapsed_share = time.time() - _share_t0
                # Validate against the same rules extract_with_retry uses, so
                # we don't pin a junk URL onto _runtime.agent_share_urls.
                if (link_res and link_res.url and
                        validate_link(agent_key, link_res.url)):
                    share_url = link_res.url
                    share_kind = "public"
                    share_verified = True
                    share_label = link_res.label or f"{name} public share"
                    log(f"[{name}] Inline share-link extracted ({_elapsed_share:.1f}s): {share_url}")
                else:
                    err = (link_res.error if link_res else "no result")
                    log(f"[{name}] Inline share-link unverified ({err}, {_elapsed_share:.1f}s) "
                        f"— falling back to conversation URL silently", "INFO")
            except asyncio.TimeoutError:
                log(f"[{name}] Inline share-link timed out (90s) "
                    f"— falling back to conversation URL silently", "INFO")
            except Exception as _e:
                log(f"[{name}] Inline share-link errored ({_e}) "
                    f"— falling back to conversation URL silently", "INFO")
        # Stash for Phase 5 — agent_chat_urls already has the conversation URL,
        # but agent_share_urls carries kind/verified so the Doc builder can
        # decide whether to label "Public share" or "Conversation".
        try:
            _runtime.agent_share_urls[name] = {
                "url": share_url,
                "kind": share_kind,
                "label": share_label,
                "verified": share_verified,
            }
        except Exception:
            # _runtime is a process-level singleton — should always exist.
            # If it doesn't, Phase 5's fallback (agent_chat_urls) still works.
            pass

    return {
        "status": "done" if n_chars > 0 else "failed",
        "text": text,
        "url": conversation_url,        # conversation URL — for resume reconnect
        "_in_app_url": _in_app_url,     # in-app /documents primary — FE link
        "verified": (n_chars > 0),
        "page": page,
        "elapsed_sec": int(elapsed_sec or 0),
        "md_saved": md_saved,
    }


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
    # CUA completion check: first at 5 min (MIN_WAIT), then every 5 min.
    # 2026-04-25: dropped from 20→5 to mirror P1 cadence (catches fast finishers).
    _min_agent_wait = int(os.environ.get("MIN_AGENT_WAIT_MIN", "5")) * 60
    MIN_WAIT = {"ChatGPT": _min_agent_wait, "Gemini": _min_agent_wait, "Claude": _min_agent_wait}
    CUA_CHECK_INTERVAL = 300   # 5 min between CUA completion checks
    ARTIFACT_SCRAPE_INTERVAL = 60   # 1 min between Claude artifact-tracking scrapes (was 180; iteration #1 must pass — see init at last_artifact_scrape=0 below)

    pending = {}
    results = {}

    for name, agent in agents.items():
        # 2026-04 fix: don't drop an agent just because verify_*_generating
        # returned False. Verifiers can miss real activity (e.g. ChatGPT DR
        # lives in a cross-origin iframe that host-side selectors can't see).
        # As long as the tab exists we keep it in the round-robin — the
        # Playwright detectors + CUA fallback decide completion. If the tab
        # is truly dead, the 90-min per-agent timeout fires eventually.
        # Only skip when there's no page handle at all (tab never opened).
        if not agent.get("page"):
            results[name] = {"status": "not_verified", "text": "", "url": agent.get("url", "")}
            continue
        if not agent["verified"]:
            log(f"[{name}] verify_{name.lower()}_generating returned False but page exists — "
                f"keeping in round-robin (detectors will decide).", "WARN")
            try:
                emit_event("pipeline_warning", phase=2, agent=name.lower().replace(" ", ""),
                           message=f"{name} verification uncertain — continuing to poll",
                           details=(f"The DOM verifier couldn't confirm {name} is generating, but "
                                    "the tab is open. Playwright + CUA detectors will monitor it "
                                    "alongside the other agents. If nothing surfaces, the 90-min "
                                    "hard timeout will release it."),
                           alertType="warn")
            except Exception:
                pass
        # Use research_started_at if available (e.g., Gemini waits for "Start research")
        # so elapsed/MIN_WAIT are computed from actual research start, not submission.
        _research_t = agent.get("research_started_at", time.time())
        pending[name] = {
            "page": agent["page"],
            "url": agent["url"],
            "start_time": _research_t,
            "done_count": 0,
            "cua_confirmed": False,
            "last_heartbeat": _research_t,
            "last_cua_check": _research_t,       # CUA check gate — MIN_WAIT from research start
            "last_artifact_scrape": 0,           # 0 → iteration #1 always passes the gate (Claude opens artifact ASAP)
            "chatgpt_activity_panel_open": False,  # ChatGPT activity-strip click flag — mirror Claude pattern
            "poll_cycles": 0,                    # increments once per round-robin tick — gates iter-#3 panel-open
            "chatgpt_panel_dom_misses": 0,       # consecutive DOM "found:false" — escalates to CUA after 2
            "chatgpt_panel_cua_attempts": 0,     # capped at 1/agent/phase
            "claude_artifact_dom_misses": 0,
            "claude_artifact_cua_attempts": 0,
            "observer_text_len": 0,              # MutationObserver sets this (see B2)
        }
        # Register for mid-run input dispatcher
        platform_key = name.lower().replace(" ", "")
        _runtime.register_page(platform_key, agent["page"], agent["url"])

    if not pending:
        return results

    _runtime.phase = 2
    _runtime.sub_state = "2_parallel_polling"
    log(f"\n--- Round-robin polling {len(pending)} agents (max {max_wait_min}min each) ---")

    # ── C1: tick counter drives strict-rotation cursor ──
    # Every tick shifts the per-agent iteration order by one, so after a
    # full rotation every agent has had its turn at being processed first.
    # Fixes the "only one agent gets polled" starvation that appears when
    # an earlier agent's await_agent_decision or long CUA check eats the
    # tick's budget before later agents are reached.
    _tick_counter = 0
    # Target 5 min of cursor dwell per agent — at the default 30s poll
    # interval that's 10 ticks between full rotations, still giving each
    # agent a shot at foreground focus every single tick via the shift.
    _tick_counter_initial = 0

    while pending:
        _tick_counter += 1
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
                # If user added input during the pause, bail out of the
                # round-robin so the orchestrator can rerun Phase 2 with the
                # combined brief (matches "pause + input + resume = rerun").
                if _controls.peek_extra_context():
                    _runtime.restart_requested = True
                    log("[Round-robin] Extra context during pause — signalling Phase 2 restart")
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
                                             "last_heartbeat": time.time(),
                                             "last_cua_check": time.time(),
                                             "last_artifact_scrape": 0,
                                             "chatgpt_activity_panel_open": False,
                                             "poll_cycles": 0,
                                             "chatgpt_panel_dom_misses": 0,
                                             "chatgpt_panel_cua_attempts": 0,
                                             "claude_artifact_dom_misses": 0,
                                             "claude_artifact_cua_attempts": 0,
                                             "observer_text_len": 0}
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

        # ── Mid-run skip (from BackendSilentBanner or HumanVerifyBanner) ──
        # User hit "Skip [agent]" in the UI → _controls.skipped_agents has
        # the lowercase name. Extract whatever partial output exists from
        # that tab and drop it from `pending` so the rest of Phase 2 keeps
        # going with the remaining agents.
        _skip_name_map = {"chatgpt": "ChatGPT", "gemini": "Gemini", "claude": "Claude"}
        for _ag_key in list(_controls.skipped_agents):
            _agent_name = _skip_name_map.get(_ag_key)
            if _agent_name and _agent_name in pending:
                p = pending[_agent_name]
                log(f"[{_agent_name}] Skipped by user — extracting partial output", "WARN")
                try:
                    await browser.switch_to_page(p["page"])
                    _partial = await extract_fns[_agent_name](
                        p["page"], browser=browser, cua_client=cua_client,
                        label=_agent_name, verbose=verbose)
                except Exception as _e:
                    log(f"[{_agent_name}] Skip-extract failed: {_e}", "WARN")
                    _partial = ""
                results[_agent_name] = {
                    "status": "skipped_by_user",
                    "text": _partial or "",
                    "url": p.get("url", ""),
                    "page": p["page"],
                    "elapsed_sec": int(time.time() - p["start_time"]),
                }
                del pending[_agent_name]
                emit_event("agent_skipped", phase=2, agent=_ag_key,
                           reason="user_skip",
                           partial_chars=len(_partial or ""))
            # Whether or not the agent was actually in pending, clear it from
            # the skip set so we don't keep firing agent_skipped every tick.
            _controls.skipped_agents.discard(_ag_key)

        # ── Hard retry (close tab + re-run setup from scratch) ──
        # Unlike the soft retry (pastes a follow-up into the same tab and
        # extends the budget — handled per-agent in the timeout branch
        # below), hard retry throws away the tab and starts the agent
        # fresh. Use when the session died or the tab is otherwise
        # unrecoverable. Other agents keep running untouched.
        _hard_name_map = {"chatgpt": "ChatGPT", "gemini": "Gemini", "claude": "Claude"}
        for _agent_key in ("chatgpt", "gemini", "claude"):
            if not _controls.consume_retry_agent_hard(_agent_key):
                continue
            _agent_name = _hard_name_map.get(_agent_key)
            if not _agent_name:
                continue
            # 2026-04-25: when an agent failed pre-pending (setup/paste
            # failed during initial Phase 2 startup), `pending` won't have
            # an entry for it. Seed a stub so the hard-retry codepath below
            # can run from scratch. hard_retry_count starts at 0 since
            # there was no prior attempt counted.
            if _agent_name not in pending:
                log(f"[{_agent_name}] Hard retry requested for agent that failed pre-pending — seeding pending stub", "INFO")
                pending[_agent_name] = {
                    "page": None,
                    "url": "",
                    "start_time": time.time(),
                    "done_count": 0,
                    "cua_confirmed": False,
                    "last_heartbeat": time.time(),
                    "last_cua_check": time.time(),
                    "last_artifact_scrape": 0,
                    "chatgpt_activity_panel_open": False,
                    "poll_cycles": 0,
                    "chatgpt_panel_dom_misses": 0,
                    "chatgpt_panel_cua_attempts": 0,
                    "claude_artifact_dom_misses": 0,
                    "claude_artifact_cua_attempts": 0,
                    "observer_text_len": 0,
                    "empty_retries": 0,
                    "hard_retry_count": 0,
                }
            p = pending[_agent_name]
            _hard_count = int(p.get("hard_retry_count", 0)) + 1
            # Cap: 2 hard retries per agent per phase. Above the cap,
            # fall through to soft retry (follow-up in same tab) instead
            # of looping forever through expensive tab restarts.
            if _hard_count > 2:
                try:
                    emit_event("pipeline_warning", phase=2, agent=_agent_key,
                               message=f"{_agent_name} hit the 2-hard-retry cap — queuing a soft retry instead",
                               details="Hard retry opens a fresh tab and resubmits the brief. Two attempts have already failed. Continuing with a soft follow-up in the existing tab; use Skip to drop the agent entirely.",
                               alertType="warn")
                except Exception:
                    pass
                _controls.retry_agents.add(_agent_key)
                continue
            log(f"[{_agent_name}] Hard retry #{_hard_count} — closing tab, re-running setup", "WARN")
            try:
                emit_event("pipeline_warning", phase=2, agent=_agent_key,
                           message=f"Hard-retrying {_agent_name} — reopening tab and resubmitting brief",
                           details=f"Attempt {_hard_count}/2. Any partial output in the closed tab is discarded.",
                           alertType="retrying")
            except Exception:
                pass
            # Resolve the brief from runtime state (populated before Phase 2 kicks
            # off at line ~10050: `_runtime.original_inputs = {..., 'brief': ...}`).
            _brief_text_hr = _runtime.original_inputs.get("brief") or ""
            _brief_path_hr = None
            if _tracks_dir:
                _bp = Path(__file__).parent / "queues" / _tracks_dir.name / "documents" / "brief.md"
                if _bp.exists():
                    _brief_path_hr = str(_bp)
            # Close old tab — non-fatal if it's already gone.
            try:
                old_page = p.get("page")
                if old_page is not None:
                    await old_page.close()
            except Exception:
                pass
            # Re-run agent setup. On crash, drop the agent from pending so
            # the phase can proceed with whoever else is still healthy.
            try:
                restart = await _restart_phase2_agent(
                    _agent_name, browser, cua_client,
                    _brief_text_hr, _brief_path_hr, verbose)
            except Exception as _e:
                log(f"[{_agent_name}] Hard retry setup crashed: {_e}", "ERROR")
                try:
                    emit_event("pipeline_error", phase=2, agent=_agent_key,
                               error=f"Hard retry failed: {_e}")
                except Exception:
                    pass
                del pending[_agent_name]
                results[_agent_name] = {"status": "hard_retry_failed", "text": "",
                                         "url": "", "page": None, "elapsed_sec": 0}
                continue
            if restart is None:
                log(f"[{_agent_name}] Hard retry returned None — dropping agent", "WARN")
                del pending[_agent_name]
                results[_agent_name] = {"status": "hard_retry_failed", "text": "",
                                         "url": "", "page": None, "elapsed_sec": 0}
                continue
            new_page, verified_h = restart
            # If the restart's setup/paste failed (verified_h False AND we
            # got a non-verified page back from start_agent_no_gemini_wait
            # ok=False), the helper already emitted pipeline_error with
            # Retry/Skip actions. Drop the agent from pending so the user's
            # next Retry click cleanly re-seeds via the pre-pending path
            # above.
            if not verified_h:
                # verified_h could legitimately be False if generation
                # verification didn't land within the window — that's the
                # benign case the WARN below handles. But if start_agent
                # itself returned ok=False, the page was set up but paste
                # failed — `_restart_phase2_agent` would have returned
                # (page, False) and emitted pipeline_error already. Either
                # way, we keep `pending` populated so polling can retry,
                # but emit a clear status.
                pass
            _now = time.time()
            pending[_agent_name] = {
                "page": new_page,
                "url": new_page.url if new_page else "",
                "start_time": _now,
                "done_count": 0,
                "cua_confirmed": False,
                "last_heartbeat": _now,
                "last_cua_check": _now,
                "last_artifact_scrape": 0,
                "chatgpt_activity_panel_open": False,
                "poll_cycles": 0,
                "chatgpt_panel_dom_misses": 0,
                "chatgpt_panel_cua_attempts": 0,
                "claude_artifact_dom_misses": 0,
                "claude_artifact_cua_attempts": 0,
                "observer_text_len": 0,
                "empty_retries": 0,
                "hard_retry_count": _hard_count,
            }
            _runtime.register_page(_agent_key, new_page,
                                    new_page.url if new_page else "")
            if verified_h:
                try:
                    await inject_agent_observer(new_page, _agent_key)
                except Exception:
                    pass
                try:
                    emit_event("agent_progress", phase=2, agent=_agent_key,
                               status="generating",
                               progress=f"{_agent_name} restarted (hard retry #{_hard_count}) — running")
                except Exception:
                    pass
                log(f"[{_agent_name}] Hard retry successful ✓")
            else:
                log(f"[{_agent_name}] Hard retry tab opened but not verified yet — polling will re-check", "WARN")
                try:
                    emit_event("pipeline_warning", phase=2, agent=_agent_key,
                               message=f"{_agent_name} reopened but not verified yet",
                               details="The new tab loaded and the brief was resubmitted, but generation verification didn't land within the window. The round-robin will keep polling; verification often completes a few seconds later.",
                               alertType="warn")
                except Exception:
                    pass

        # Rotate iteration order so no agent is always "first". With 3
        # agents, the order cycles A→B→C, B→C→A, C→A→B, A→B→C, ensuring
        # that over 3 ticks every agent has been processed first.
        _pending_keys = list(pending.keys())
        if _pending_keys:
            _shift = _tick_counter % len(_pending_keys)
            _pending_keys = _pending_keys[_shift:] + _pending_keys[:_shift]

        for name in _pending_keys:
            p = pending[name]
            elapsed = time.time() - p["start_time"]
            # Per-agent cycle counter (used for "give research time to settle"
            # gate before opening Claude/ChatGPT panels — see iter-#3 logic
            # below). Increment ONCE per round-robin tick per agent.
            p["poll_cycles"] = p.get("poll_cycles", 0) + 1

            # ── C6: cursor foreground + partial-content refresh ──
            # Bring this agent's tab to the front before any scrape/check so
            # its MutationObserver has the freshest token stream (Chromium
            # throttles background tabs less under Playwright than a normal
            # browser, but foregrounding still produces materially fresher
            # data — especially after a long blocking await on another agent).
            try:
                await browser.switch_to_page(p["page"])
            except Exception as _sw_err:
                log(f"[{name}] switch_to_page at cursor start failed: {_sw_err}", "WARN")

            # Timeout
            if elapsed > max_wait_min * 60:
                log(f"[{name}] Timeout ({max_wait_min}min)", "WARN")
                agent_key_to = normalize_agent_key(name)
                # Extract partial text now so the user can decide whether it's
                # enough to proceed with.
                try:
                    await browser.switch_to_page(p["page"])
                    partial_text = await extract_fns[name](p["page"], browser=browser,
                        cua_client=cua_client, label=name, verbose=verbose)
                except Exception as e:
                    log(f"[{name}] Extraction after timeout failed: {e}", "WARN")
                    partial_text = ""
                partial_len = len(partial_text or "")
                # Live source count for concrete banner ("42 sources so far")
                partial_sources = 0
                try:
                    tr_path = _tracks_dir / f"{agent_key_to}.json" if _tracks_dir else None
                    if tr_path and tr_path.exists():
                        tr = json.loads(tr_path.read_text(encoding="utf-8"))
                        partial_sources = tr.get("sources", 0) or 0
                except Exception:
                    pass
                _sources_note = f"{partial_sources} sources, " if partial_sources else ""
                try:
                    emit_event("pipeline_warning", phase=2, agent=agent_key_to,
                               message=f"{name} timed out after {max_wait_min} min — {_sources_note}{partial_len} chars extracted",
                               details=("The agent exceeded its research budget. "
                                        "Retry sends a 'finish + regenerate' follow-up (adds ~15 min). "
                                        "Wait grants another 15 min without nudging the agent. "
                                        "Skip drops this agent entirely; others proceed."),
                               alertType="warn",
                               actions=[
                                   {"id": "retry", "label": "Retry",
                                    "style": "primary",
                                    "command": {"action": "retry_agent", "agent": agent_key_to}},
                                   {"id": "wait", "label": "Wait",
                                    "style": "default",
                                    "command": {"action": "wait_longer_agent", "agent": agent_key_to}},
                                   {"id": "skip", "label": "Skip",
                                    "style": "default",
                                    "command": {"action": "skip_agent", "agent": agent_key_to}},
                               ])
                except Exception:
                    pass
                # Wait up to 5 min for decision. Default (timeout) = wait_longer
                # — keep polling rather than silently accepting partial output.
                decision = await _controls.await_agent_decision(agent_key_to, timeout=300.0)
                log(f"[{name}] Timeout user decision: {decision}")
                if decision == "stop":
                    # Let outer stop handler clean up on next iteration
                    break
                if decision == "skip":
                    # skipped_agents handler at the top of the loop will pick
                    # this up on the next iteration and finalize with
                    # status=skipped_by_user. Don't touch pending here.
                    continue
                if decision == "retry":
                    try:
                        emit_event("pipeline_warning", phase=2, agent=agent_key_to,
                                   message=f"Retrying {name} — sending follow-up to continue research",
                                   alertType="retrying")
                    except Exception:
                        pass
                    followup = (
                        "Your previous response hit our time budget. Please continue the research "
                        "and output the complete, thorough final report now — include every source, "
                        "section, and finding you have. No preamble."
                    )
                    try:
                        await browser.switch_to_page(p["page"])
                        await paste_followup(p["page"], followup, name.lower(), label=f"{name}-retry")
                    except Exception as e:
                        log(f"[{name}] Retry follow-up failed: {e}", "WARN")
                    # Extend budget by 15 min by rewinding start_time; reset done state
                    p["start_time"] = time.time() - (max_wait_min * 60) + (15 * 60)
                    p["done_count"] = 0
                    p["cua_confirmed"] = False
                    p["last_cua_check"] = time.time()
                    p.pop("_cached_text", None)
                    p["empty_retries"] = 0
                    continue
                if decision in ("wait_longer", "timeout"):
                    # User picked "Wait" (or auto-default timeout) — grant
                    # another 15 min without pinging the agent. Keep polling.
                    try:
                        emit_event("pipeline_warning", phase=2, agent=agent_key_to,
                                   message=f"Extending {name}'s budget by 15 min — still waiting for completion",
                                   alertType="retrying")
                    except Exception:
                        pass
                    p["start_time"] = time.time() - (max_wait_min * 60) + (15 * 60)
                    continue
                # Legacy 'continue_partial' only — no button surfaces this
                # anymore, but keep handling for in-flight commands.
                results[name] = {"status": "timeout_partial", "text": partial_text or "",
                                 "url": p.get("url", ""), "page": p["page"]}
                del pending[name]
                continue

            # ── Mid-run session expiry check ──
            # Agent tabs sometimes get logged out silently (cookie expiry,
            # background re-auth failure). Catch it here so the user gets a
            # clear banner instead of the polling loop churning indefinitely
            # against a login page. Throttled — one check every 2 min per agent.
            # Require 2 consecutive detections before firing the alert to avoid
            # false alarms from transient modals / loading states.
            _last_auth_check = p.get("last_auth_check", 0)
            if (time.time() - _last_auth_check) > 120:
                p["last_auth_check"] = time.time()
                agent_key_auth = normalize_agent_key(name)
                platform_key = name.lower().replace(" ", "")
                expired, reason = await detect_session_expiry(p["page"], platform_key, name)
                if not expired:
                    p["session_expiry_hits"] = 0
                else:
                    p.setdefault("session_expiry_hits", 0)
                    p["session_expiry_hits"] += 1
                if expired and p.get("session_expiry_hits", 0) < 2:
                    log(f"[{name}] Possible session expiry ({reason}) — waiting for 2nd confirmation before alerting", "WARN")
                    expired = False  # Suppress alert this tick
                if expired:
                    log(f"[{name}] Session expired mid-run ({reason}) — confirmed by 2 consecutive checks", "WARN")
                    p["session_expiry_hits"] = 0  # reset for next time
                    try:
                        emit_event("pipeline_error", phase=2, agent=agent_key_auth,
                                   error=f"{name} session expired mid-run — re-authenticate in the browser and tap Retry",
                                   details=(f"The {name} tab drifted to a login page ({reason}). "
                                            "This usually means your session cookie expired or the platform "
                                            "forced a re-auth. Log in again in the browser on your PC, then "
                                            "hit Retry. Skip drops this agent."),
                                   actions=[
                                       {"id": "retry", "label": "I've logged in — Retry",
                                        "style": "primary",
                                        "command": {"action": "retry_agent", "agent": agent_key_auth}},
                                       {"id": "skip", "label": "Skip agent",
                                        "style": "default",
                                        "command": {"action": "skip_agent", "agent": agent_key_auth}},
                                   ])
                    except Exception:
                        pass
                    # Block this agent's polling until user decides. Other
                    # agents keep polling (they don't hit this await).
                    auth_decision = await _controls.await_agent_decision(agent_key_auth, timeout=1800.0)
                    log(f"[{name}] Session-expiry decision: {auth_decision}")
                    if auth_decision == "stop":
                        break
                    if auth_decision == "skip":
                        # Existing skipped_agents handler will finalize on next tick
                        continue
                    if auth_decision == "retry":
                        # Refresh the tab so the agent's (now logged-in) session cookie
                        # lands, then reset polling state. Don't extend budget — this
                        # is the user's re-auth, not a new research run.
                        try:
                            await p["page"].reload(wait_until="domcontentloaded", timeout=15000)
                            await asyncio.sleep(3)
                        except Exception as _e:
                            log(f"[{name}] Reload after re-auth failed: {_e}", "WARN")
                        p["last_auth_check"] = time.time()
                        continue
                    # 'continue_partial' / 'timeout' — user idle; keep polling
                    # with the stale session (likely 30min re-grace from platforms)
                    continue

            # DOM scrape (primary); MutationObserver handles token-level stream separately.
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

            # Claude artifact tracking — open the FIRST artifact and keep it open
            # so subsequent polls re-read live (URLs / steps / sections) without
            # re-clicking. Auto-close removed: the second artifact (final report) is
            # detected/opened separately by extract_claude_response at completion.
            #
            # 2026-04-26 (v3): iter-#3 settle gate — wait until ≥3 polling cycles
            # OR ≥180s wall-clock (whichever first) so research is actually
            # ongoing and the artifact card has spawned. Same gate applied to
            # ChatGPT below for symmetry. After 2 consecutive DOM "no artifact"
            # readings (after the gate clears), escalate to CUA tier-3 once.
            # One-shot Claude page refresh at cycle 2 — unstick prophylaxis.
            # Claude.ai sometimes hangs DOM mid-research even though server-side
            # generation continues. A single reload mid-research re-mounts the
            # conversation + artifact card from server state without losing any
            # research progress (research is server-side; refresh is DOM-only).
            # Runs BEFORE the artifact-open gate clears at cycle 3, so iter 3's
            # first DOM probe meets a fresh DOM.
            if (name == "Claude"
                    and p.get("poll_cycles", 0) == 2
                    and not p.get("claude_refreshed_once")):
                try:
                    log("[Claude] one-shot page refresh at cycle=2 (unstick prophylaxis)")
                    await p["page"].reload(wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(3.0)
                except Exception as _re:
                    log(f"[Claude] refresh failed: {_re}", "WARN")
                p["claude_refreshed_once"] = True

            _claude_gate_ok = (p.get("poll_cycles", 0) >= 3 or elapsed >= 180)
            if (name == "Claude" and _claude_gate_ok and
                    (time.time() - p.get("last_artifact_scrape", 0)) > ARTIFACT_SCRAPE_INTERVAL):
                try:
                    artifact_data = await scrape_claude_artifact_tracking(
                        p["page"], browser=browser, cua_client=cua_client,
                        verbose=verbose, keep_open=True,
                        already_open=p.get("artifact_panel_open", False))
                    if artifact_data:
                        if not p.get("artifact_panel_open"):
                            log(f"[Claude] artifact panel opened (first time) at "
                                f"elapsed={int(elapsed)}s, cycle={p.get('poll_cycles')}")
                        p["artifact_panel_open"] = True
                        p["claude_artifact_dom_misses"] = 0  # reset on success
                        # Mirror onto runtime singleton so extract_and_record_agent
                        # (which has no `p` handle) can close-1 before clicking the
                        # final artifact card. See extract_claude_response signature.
                        try:
                            _runtime.claude_artifact_panel_open = True
                        except Exception:
                            pass
                        if artifact_data.get("source_urls"):
                            for key in ("source_urls", "steps", "sections", "tool_uses"):
                                if artifact_data.get(key):
                                    existing = progress.get(key, []) or []
                                    merged = list(dict.fromkeys(existing + artifact_data[key]))
                                    progress[key] = merged
                            if artifact_data.get("sources", 0) > progress.get("sources", 0):
                                progress["sources"] = artifact_data["sources"]
                            if artifact_data.get("partial_text_len", 0) > progress.get("partial_text_len", 0):
                                progress["partial_text_len"] = artifact_data["partial_text_len"]
                            progress["artifact_count"] = artifact_data.get("artifact_count", 0)
                            save_track("Claude", {**artifact_data, "source": "artifact_scrape"})
                            scrape_ok = True
                            log(f"[Claude] Artifact tracking: {len(artifact_data.get('source_urls', []))} URLs, "
                                f"{len(artifact_data.get('steps', []))} steps, "
                                f"{len(artifact_data.get('sections', []))} sections")
                    else:
                        # No artifact detected — count as DOM miss for CUA escalation.
                        if not p.get("artifact_panel_open"):
                            p["claude_artifact_dom_misses"] = p.get("claude_artifact_dom_misses", 0) + 1
                            log(f"[Claude] artifact DOM miss "
                                f"#{p['claude_artifact_dom_misses']} at cycle={p.get('poll_cycles')}",
                                "DEBUG")
                    p["last_artifact_scrape"] = time.time()
                except Exception as e:
                    log(f"[Claude] Artifact tracking scrape failed: {e}", "WARN")
                    p["last_artifact_scrape"] = time.time()

                # CUA tier-3 escalation — fires after 2 consecutive DOM misses,
                # capped at 1/agent/phase. Tries to find + click the FIRST
                # artifact card visually.
                if (not p.get("artifact_panel_open")
                        and p.get("claude_artifact_dom_misses", 0) >= 2
                        and p.get("claude_artifact_cua_attempts", 0) == 0
                        and cua_client):
                    log(f"[Claude] DOM missed artifact 2x — escalating to CUA tier-3 "
                        f"(cycle={p.get('poll_cycles')})")
                    try:
                        emit_event("tier_transition", phase=2, agent="claude",
                                   op="open_artifact_1", from_tier="dom",
                                   to_tier="cua", reason="dom_2_misses")
                    except Exception:
                        pass
                    p["claude_artifact_cua_attempts"] = 1
                    async def _claude_p2_cua():
                        return await asyncio.wait_for(
                            agent_loop(cua_client, browser,
                                PROMPT_OPEN_CLAUDE_SOURCE_ARTIFACT,
                                "Open the FIRST artifact card (research/sources tracking) "
                                "in the Claude conversation. NEVER click the last artifact.",
                                model=CUA_MODEL, max_iterations=5,
                                verbose=verbose, target_page=p["page"]),
                            timeout=120.0)
                    try:
                        cua_res = await _shadow_observed_cua(
                            p["page"], hotspot_id="7d", phase=2, platform="claude",
                            current_step="open_artifact_1",
                            context_hint=f"DOM 2-miss at cycle={p.get('poll_cycles')}",
                            expected_outcome="right panel mounts artifact-1 checklist",
                            cua_coro_factory=_claude_p2_cua)
                        out = ((cua_res or {}).get("text") or "").lower()
                        if "panel: open" in out or "panel: already_open" in out:
                            p["artifact_panel_open"] = True
                            try:
                                _runtime.claude_artifact_panel_open = True
                            except Exception:
                                pass
                            log("[Claude] artifact panel opened via CUA tier-3")
                        else:
                            log(f"[Claude] CUA tier-3 didn't confirm panel open: {out[:120]}", "WARN")
                    except asyncio.TimeoutError:
                        log("[Claude] CUA tier-3 timed out after 120s", "WARN")
                    except Exception as _ce:
                        log(f"[Claude] CUA tier-3 failed: {_ce}", "WARN")

            # ChatGPT activity-strip open — DOM tier-1 → CUA tier-3 fallback.
            # Strip rendered as styled <div> at bottom of chat thread reading
            # "Looking into X... N searches". Side panel with full step list +
            # source URLs only mounts AFTER click. Without it polling sees only
            # the truncated preview.
            #
            # 2026-04-26 (v3) lessons from 3 failed runs:
            #  - v1 narrow selector (button/[role="button"]) matched 0
            #    candidates because strip is a bare <div> — fix: walk * with
            #    full pointer/mouse event chain (see _open_chatgpt_activity_panel).
            #  - Iter-#1 fired before strip rendered — fix: iter-#3 gate
            #    (poll_cycles>=3 or elapsed>=180s — whichever first).
            #  - DOM "click" silently swallowed — fix: post-click verifier
            #    (`_verify_chatgpt_panel_open`) confirms side panel actually
            #    rendered before flipping the flag.
            #  - After 2 DOM misses → CUA tier-3 fallback (capped at 1/phase).
            _cgpt_gate_ok = (p.get("poll_cycles", 0) >= 3 or elapsed >= 180)
            if (name == "ChatGPT" and _cgpt_gate_ok and
                    not p.get("chatgpt_activity_panel_open")):
                try:
                    res = await _open_chatgpt_activity_panel(p["page"])
                    cands = (res or {}).get("candidates", 0)
                    if not res or not res.get("found"):
                        p["chatgpt_panel_dom_misses"] = p.get("chatgpt_panel_dom_misses", 0) + 1
                        log(f"[ChatGPT] panel DOM miss #{p['chatgpt_panel_dom_misses']} "
                            f"(cycle={p.get('poll_cycles')}, walked_hits={cands}) — "
                            f"strip not yet rendered or wording changed", "DEBUG")
                    elif res.get("alreadyExpanded"):
                        p["chatgpt_activity_panel_open"] = True
                        p["chatgpt_panel_dom_misses"] = 0
                        log(f"[ChatGPT] activity panel already expanded at "
                            f"elapsed={int(elapsed)}s — label: \"{res.get('label','')[:80]}\"")
                    elif res.get("clicked"):
                        # Verify panel actually rendered (mitigates silent click failure).
                        await asyncio.sleep(2.0)
                        verified = await _verify_chatgpt_panel_open(p["page"])
                        if verified:
                            p["chatgpt_activity_panel_open"] = True
                            p["chatgpt_panel_dom_misses"] = 0
                            log(f"[ChatGPT] activity panel opened via DOM at "
                                f"elapsed={int(elapsed)}s — label: \"{res.get('label','')[:80]}\" "
                                f"clickedTag={res.get('clickedTag','?')}")
                        else:
                            p["chatgpt_panel_dom_misses"] = p.get("chatgpt_panel_dom_misses", 0) + 1
                            log(f"[ChatGPT] DOM clicked but panel didn't render — "
                                f"miss #{p['chatgpt_panel_dom_misses']}", "WARN")
                    else:
                        p["chatgpt_panel_dom_misses"] = p.get("chatgpt_panel_dom_misses", 0) + 1
                        log(f"[ChatGPT] panel found but click failed — "
                            f"label: \"{res.get('label','')[:80]}\" "
                            f"err={res.get('error','?')}", "WARN")
                except Exception as e:
                    log(f"[ChatGPT] activity panel open failed: {e}", "WARN")
                    p["chatgpt_panel_dom_misses"] = p.get("chatgpt_panel_dom_misses", 0) + 1

                # CUA tier-3 escalation after 2 DOM misses (capped at 1/phase).
                if (not p.get("chatgpt_activity_panel_open")
                        and p.get("chatgpt_panel_dom_misses", 0) >= 2
                        and p.get("chatgpt_panel_cua_attempts", 0) == 0
                        and cua_client):
                    log(f"[ChatGPT] DOM missed strip 2x — escalating to CUA tier-3 "
                        f"(cycle={p.get('poll_cycles')})")
                    try:
                        emit_event("tier_transition", phase=2, agent="chatgpt",
                                   op="open_activity_panel", from_tier="dom",
                                   to_tier="cua", reason="dom_2_misses")
                    except Exception:
                        pass
                    p["chatgpt_panel_cua_attempts"] = 1
                    async def _cgpt_p2_cua():
                        return await asyncio.wait_for(
                            agent_loop(cua_client, browser,
                                PROMPT_OPEN_CHATGPT_SOURCE_PANEL,
                                "Open the activity strip at the bottom of this ChatGPT "
                                "Deep Research conversation. ONE click only. Verify the "
                                "side panel slides out before reporting.",
                                model=CUA_MODEL, max_iterations=5,
                                verbose=verbose, target_page=p["page"]),
                            timeout=120.0)
                    try:
                        cua_res = await _shadow_observed_cua(
                            p["page"], hotspot_id="7c", phase=2, platform="chatgpt",
                            current_step="open_activity_panel",
                            context_hint=f"DOM 2-miss at cycle={p.get('poll_cycles')}",
                            expected_outcome="side panel mounts on right with step list",
                            cua_coro_factory=_cgpt_p2_cua)
                        out = ((cua_res or {}).get("text") or "").lower()
                        if "panel: open" in out or "panel: already_open" in out:
                            p["chatgpt_activity_panel_open"] = True
                            log("[ChatGPT] activity panel opened via CUA tier-3")
                        else:
                            log(f"[ChatGPT] CUA tier-3 didn't confirm panel open: {out[:120]}", "WARN")
                    except asyncio.TimeoutError:
                        log("[ChatGPT] CUA tier-3 timed out after 120s", "WARN")
                    except Exception as _ce:
                        log(f"[ChatGPT] CUA tier-3 failed: {_ce}", "WARN")

            # Emit agent_progress to frontend (critical for real-time UI)
            agent_key = normalize_agent_key(name)
            # If scrape failed we don't know the agent's real status — keep
            # elapsed-time progress text but omit stale/fake fields
            _status_val = progress.get("status") if scrape_ok else "generating"
            _progress_val = progress.get("progress") if scrape_ok else None
            if not _progress_val:
                _progress_val = f"Researching... ({int(time.time() - p['start_time']) // 60}m elapsed)"
            elapsed_sec = int(time.time() - p["start_time"])

            # DOM partial text length + MutationObserver stream.
            # Observer fires every ~500ms as tokens arrive (see inject_agent_observer);
            # DOM scrape runs every 30s. Use whichever is larger so the progress bar
            # climbs monotonically even between DOM scrapes.
            _obs = get_observer_state(p["page"])
            _obs_len = int(_obs.get("observer_text_len", 0) or 0)
            _obs_preview = str(_obs.get("observer_preview", "") or "")
            _partial_text_len = max(progress.get("partial_text_len", 0) or 0, _obs_len)
            p["observer_text_len"] = _obs_len  # Keep shared-dict snapshot fresh

            # ── Stuck-agent detection ──
            # Compare current text length AND source count against the last-
            # growth checkpoint. Only alert if BOTH haven't moved for 20 min
            # AND the agent isn't in a known "planning/thinking" status.
            # These gates avoid false alarms on agents mid-research (planning
            # phases are often 10+ min with no text growth but active sources).
            agent_key_stuck = normalize_agent_key(name)
            _src_count = int(progress.get("sources", 0) or 0)
            p.setdefault("last_growth_len", 0)
            p.setdefault("last_growth_sources", 0)
            p.setdefault("last_growth_time", p["start_time"])
            p.setdefault("stuck_warned_at", 0.0)
            if _partial_text_len > p["last_growth_len"] or _src_count > p["last_growth_sources"]:
                p["last_growth_len"] = max(p["last_growth_len"], _partial_text_len)
                p["last_growth_sources"] = max(p["last_growth_sources"], _src_count)
                p["last_growth_time"] = time.time()
            no_growth_secs = time.time() - p["last_growth_time"]
            since_warn = time.time() - p["stuck_warned_at"]
            _active_statuses = ("planning", "thinking", "researching", "searching")
            status_is_active = (_status_val or "").lower() in _active_statuses
            # Require: elapsed >20min, no-growth >20min, no active-status
            # signal, at least 120s since last warn (avoid spam on dedup miss).
            if elapsed > 1200 and no_growth_secs > 1200 and since_warn > 900 and not status_is_active:
                p["stuck_warned_at"] = time.time()
                try:
                    emit_event("pipeline_warning", phase=2, agent=agent_key_stuck,
                               message=f"{name} stalled — no text or source growth for {int(no_growth_secs/60)} min (currently {_partial_text_len} chars, {_src_count} sources)",
                               details=("The agent's output hasn't grown in a while. "
                                        "Retry sends a 'please continue' follow-up. "
                                        "Wait grants another 15 min of budget. "
                                        "Skip drops this agent."),
                               alertType="warn",
                               actions=[
                                   {"id": "retry", "label": "Retry",
                                    "style": "primary",
                                    "command": {"action": "poke_agent", "agent": agent_key_stuck}},
                                   {"id": "wait", "label": "Wait",
                                    "style": "default",
                                    "command": {"action": "wait_longer_agent", "agent": agent_key_stuck}},
                                   {"id": "skip", "label": "Skip",
                                    "style": "default",
                                    "command": {"action": "skip_agent", "agent": agent_key_stuck}},
                               ])
                except Exception:
                    pass
                # Non-blocking: we don't await here since other agents are
                # still healthy. The command bus applies the user's choice
                # asynchronously — check on next tick.
            # Apply any async decision that landed since last tick.
            if _controls.consume_poke_agent(agent_key_stuck):
                log(f"[{name}] User poked — sending 'please continue' follow-up")
                try:
                    emit_event("pipeline_warning", phase=2, agent=agent_key_stuck,
                               message=f"Poking {name} — sending 'please continue' prompt",
                               alertType="retrying")
                    await browser.switch_to_page(p["page"])
                    await paste_followup(p["page"], "Please continue — output the rest of your research.",
                                         name.lower(), label=f"{name}-poke")
                except Exception as _e:
                    log(f"[{name}] Poke failed: {_e}", "WARN")
                p["last_growth_time"] = time.time()
            if _controls.consume_wait_longer_agent(agent_key_stuck):
                log(f"[{name}] User granted 10 more minutes")
                p["last_growth_time"] = time.time()

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
                    sourceUrls=progress.get("source_urls", []),
                    sections=progress.get("sections", []),
                    partialTextLen=_partial_text_len,
                    partialTextPreview=_obs_preview,
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

            # ── Playwright-primary completion check (2026-04-25 strict) ─────
            # The detect_completion_* functions return (done, reason, snap)
            # where snap = {text_len, sources, steps}. They report done=True
            # ONLY when the platform's definitive done-marker is present
            # (Stop button gone + "Thought for X" / Share & Export visible /
            # research_complete card). Caller-side 2-cycle gate confirms
            # text + sources + steps are all flat across 2 polling cycles
            # before extracting — eliminates the partial_len>5000,
            # artifacts>=2, transient-keyword false positives.
            detect_fn = DETECT_FNS.get(name)
            if detect_fn and elapsed >= MIN_WAIT.get(name, 180):
                try:
                    dom_done, dom_reason, snap = await detect_fn(p["page"])
                except Exception as _de:
                    log(f"[{name}] detect_completion error: {_de}", "WARN")
                    dom_done, dom_reason, snap = (False, f"detect_error: {_de}", {})
                p.setdefault("flat_history", [])
                p.setdefault("done_marker_first_at", 0.0)
                p.setdefault("extraction_attempts", 0)
                if not dom_done:
                    # Definitive done-marker absent — discard any flat history.
                    if p["flat_history"]:
                        log(f"[{name}] Done-marker lost — clearing flat_history ({dom_reason})")
                    p["flat_history"] = []
                    p["done_marker_first_at"] = 0.0
                else:
                    # Done-marker present — append snapshot. Need 3 snapshots
                    # over ≥240s (2 polling cycles at 120s) all flat to extract.
                    if p["done_marker_first_at"] == 0.0:
                        p["done_marker_first_at"] = time.time()
                    p["flat_history"].append((
                        int(snap.get("text_len", 0) or 0),
                        int(snap.get("sources", 0) or 0),
                        int(snap.get("steps", 0) or 0),
                    ))
                    p["flat_history"] = p["flat_history"][-3:]
                    log(f"[{name}] Done-marker confirmed #{len(p['flat_history'])} — "
                        f"{dom_reason}; snap={snap}")
                    elapsed_done = time.time() - p["done_marker_first_at"]
                    if len(p["flat_history"]) < 3 or elapsed_done < 240:
                        # Not enough samples yet — keep polling.
                        continue
                    t0, s0, st0 = p["flat_history"][0]
                    t1, s1, st1 = p["flat_history"][1]
                    t2, s2, st2 = p["flat_history"][2]
                    flat = (t0 == t1 == t2 and s0 == s1 == s2 and st0 == st1 == st2)
                    if not flat:
                        log(f"[{name}] Done-marker present but signals still moving — "
                            f"text {t0}→{t1}→{t2}, sources {s0}→{s1}→{s2}, "
                            f"steps {st0}→{st1}→{st2}; keep polling")
                        # Trim history so we re-anchor on the next snapshot —
                        # if a single late mutation slipped through, the next
                        # tick's snapshot becomes the new baseline.
                        p["flat_history"] = p["flat_history"][-1:]
                        continue
                    p["extraction_attempts"] += 1
                    log(f"[{name}] CONFIRMED DONE — done-marker + 2 cycles flat "
                        f"(text={t2}, sources={s2}, steps={st2}, "
                        f"elapsed_since_marker={int(elapsed_done)}s). "
                        f"Starting extract_and_record (attempt {p['extraction_attempts']}/3)")
                    _queue_dir = (Path(__file__).parent / "queues" / _tracks_dir.name) \
                                 if _tracks_dir else None
                    res = await extract_and_record_agent(
                        name, p["page"], browser, cua_client,
                        queue_dir=_queue_dir,
                        elapsed_sec=int(elapsed),
                        verbose=verbose,
                    )
                    # 2026-04-25: markdown-as-primary. "done" means text>0 +
                    # in-app primary emitted. res["url"] is the conversation
                    # URL (page.url) for resume; res["_in_app_url"] is the
                    # FE primary /documents?open=… link.
                    if res["status"] == "done":
                        _runtime.unregister_page(
                            name.lower().replace(" ", ""),
                            final_status="done",
                        )
                        _runtime.agent_chat_urls[
                            name.lower().replace(" ", "")
                        ] = res.get("url") or ""
                        results[name] = res
                        del pending[name]
                        log(f"[{name}] Extraction complete — "
                            f"{len(res['text'])} chars, "
                            f"in_app={(res.get('_in_app_url') or '')[:60]}, "
                            f"convo={(res.get('url') or '')[:60]}")
                        continue
                    # Extraction produced nothing usable. Reset state so
                    # we re-confirm before another attempt. After 3 failed
                    # attempts surface a pipeline_error with Retry/Skip.
                    log(f"[{name}] Extraction attempt {p['extraction_attempts']}/3 "
                        f"returned no content — reverting to polling", "WARN")
                    p["flat_history"] = []
                    p["done_marker_first_at"] = 0.0
                    if p["extraction_attempts"] >= 3:
                        emit_event("pipeline_error", phase=2, agent=agent_key,
                                   error=f"{name} extraction failed after 3 confirmed-done attempts",
                                   details=(f"The Playwright detector confirmed {name} was done, "
                                            "but 3 extraction attempts returned no content. "
                                            "Retry runs the extraction pipeline again. "
                                            "Skip drops this agent from the results."),
                                   actions=[
                                       {"id": "retry", "label": "Retry extraction",
                                        "style": "primary"},
                                       {"id": "skip",  "label": "Skip agent",
                                        "style": "default"},
                                   ])
                        decision = await _controls.await_agent_decision(agent_key, timeout=600.0)
                        log(f"[{name}] Extraction-failed decision: {decision}")
                        if decision == "retry":
                            p["extraction_attempts"] = 0
                            p["flat_history"] = []
                            continue
                        if decision == "skip":
                            results[name] = {"status": "skipped_by_user",
                                             "text": "", "url": "",
                                             "page": p["page"],
                                             "elapsed_sec": int(elapsed)}
                            del pending[name]
                            emit_event("agent_skipped", phase=2, agent=agent_key,
                                       reason="extraction_failure_skip")
                            continue
                        if decision == "stop":
                            break
                    continue

            # Check completion — CUA-primary fallback (only if Playwright was
            # not confident within the MIN_WAIT + budget window). CUA checks
            # every 5 min per agent (cost-effective, actually works).
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
                model=CUA_MODEL, max_iterations=3, verbose=verbose,
                phase=2, agent_name=normalize_agent_key(name), target_page=p["page"])
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

                # Gemini-specific: validate completion via source count + content length
                # Gemini Deep Research typically finds 10+ sources. If we have 0 sources
                # and minimal text early in the run, the "done" verdict is likely false.
                if name == "Gemini" and elapsed < (max_wait_min * 60 * 0.7):
                    try:
                        _gm_progress = await scrape_progress_gemini(p["page"])
                        _gm_sources = _gm_progress.get("sources", 0)
                        _gm_text = _gm_progress.get("partial_text_len", 0)
                        _gm_steps = len(_gm_progress.get("steps", []))
                        if _gm_sources < 3 and _gm_text < 2000:
                            log(f"[Gemini] CUA says done but only {_gm_sources} sources, "
                                f"{_gm_text} chars, {_gm_steps} steps at {int(elapsed/60)}m "
                                f"— likely still researching. Reverting.", "WARN")
                            p["done_count"] = 0
                            p["cua_confirmed"] = False
                            p["last_cua_check"] = time.time()
                            emit_event("agent_progress", phase=2, agent="gemini",
                                       status="generating",
                                       progress=f"Still researching — {_gm_sources} sources so far",
                                       elapsedSec=int(elapsed))
                            continue
                    except Exception:
                        pass

                # Claude-specific: validate completion via artifact count.
                # Research mode on Opus 4.7 with Adaptive Thinking USED to
                # produce TWO artifacts — (1) references, (2) the final
                # report. The 2026 layout collapses to ONE artifact card
                # whose text reads "Research complete · N sources · Xm Ys"
                # AND contains the full report inline. So:
                #
                #   • If body-text matches the "Research complete" marker
                #     → trust the done verdict regardless of artifact count
                #     (the marker only appears when streaming ends).
                #   • Else, fall through to the legacy artifact-count gate:
                #     < 80% budget + < 2 → revert to polling; ≥ 80% + < 2 →
                #     hard-fail with Retry/Skip/Wait modal.
                if name == "Claude":
                    try:
                        _art_count = await _count_claude_artifacts(p["page"])
                    except Exception:
                        _art_count = 2  # on DOM query failure, trust extraction
                    # 2026-04-26: bypass the artifact-count gate when the
                    # modern "Research complete · N sources · Xm Ys" marker
                    # is present. This lets the 1-artifact-card layout pass
                    # without nudging or hard-failing.
                    _claude_completion_marker = False
                    try:
                        _claude_completion_marker = bool(await p["page"].evaluate(
                            """() => /research\\s+complete(?:d)?\\s*[\\s·•—\\-]+\\d[\\d,]*\\s+sources?/i.test(
                                document.body?.innerText || ''
                            )"""
                        ))
                    except Exception:
                        _claude_completion_marker = False
                    if _claude_completion_marker:
                        log(f"[Claude] Modern completion marker detected — accepting 1-artifact layout (art_count={_art_count})", "INFO")
                        # Fall through to extraction (skip both gates below).
                    elif _art_count < 2 and elapsed < (max_wait_min * 60 * 0.8):
                        log(f"[Claude] CUA says done but only {_art_count} artifact(s) at "
                            f"{int(elapsed/60)}m — likely still researching. Reverting.", "WARN")
                        p["done_count"] = 0
                        p["cua_confirmed"] = False
                        p["last_cua_check"] = time.time()
                        emit_event("agent_progress", phase=2, agent="claude",
                                   status="generating",
                                   progress=f"Still researching — only {_art_count} artifact(s) so far",
                                   elapsedSec=int(elapsed))
                        continue
                    elif not _claude_completion_marker and _art_count < 2:
                        # ── C2: one-shot auto-nudge before the hard-fail modal ──
                        # Give Claude 90s to produce artifact 2 after an explicit
                        # ask, before interrupting the user. Fires once per agent
                        # per phase (p["nudged_artifact"]).
                        if not p.get("nudged_artifact"):
                            p["nudged_artifact"] = True
                            nudge_art = (
                                "Your research is incomplete — the final comprehensive report "
                                "artifact is missing. Please produce the complete research "
                                "document artifact now — include every section, finding, and "
                                "source. This is the deliverable document, not the references list."
                            )
                            try:
                                emit_event("agent_progress", phase=2, agent="claude",
                                           status="nudging",
                                           progress="Nudging Claude to publish artifact 2 (90s)…")
                                await browser.switch_to_page(p["page"])
                                await paste_followup(p["page"], nudge_art, "claude",
                                                     label="Claude-nudge-artifact")
                                log(f"[Claude] Sent artifact-2 nudge — waiting 90s")
                                await asyncio.sleep(90)
                            except Exception as _ne:
                                log(f"[Claude] Artifact nudge failed: {_ne}", "WARN")
                            # Rewind so next CUA tick re-checks artifact count
                            p["done_count"] = 0
                            p["cua_confirmed"] = False
                            p["last_cua_check"] = time.time()
                            p["start_time"] = time.time() - (max_wait_min * 60) + (10 * 60)
                            continue
                        # Hard-fail path — budget 80%+ spent and the 2nd
                        # artifact never materialized. Don't silently accept
                        # the 1st one (that's the references, not the report).
                        log(f"[Claude] Hard-fail: {int(elapsed/60)}m elapsed with only "
                            f"{_art_count} artifact(s) — final document missing", "ERROR")
                        agent_key_hf = "claude"
                        # agent_link_failed → AgentLinkFailedBanner with
                        # Retry · Skip. pipeline_warning lands on a phase-
                        # level surface the user won't notice.
                        try:
                            emit_event("agent_link_failed", phase=2, agent=agent_key_hf,
                                       attempts=1,
                                       lastError=f"Claude produced only {_art_count} artifact — final document missing")
                        except Exception:
                            pass
                        p.setdefault("hf_timeouts", 0)
                        decision = await _controls.await_agent_decision(agent_key_hf, timeout=300.0)
                        log(f"[Claude] 2-artifact hard-fail decision: {decision}")
                        if decision == "stop":
                            break
                        if decision == "skip":
                            continue
                        if decision == "retry":
                            p["hf_timeouts"] = 0
                            followup = (
                                "Your research is incomplete — the final comprehensive report artifact is missing. "
                                "Please produce the complete research document artifact now — include every section, "
                                "finding, and source. This is the deliverable document, not the references list."
                            )
                            try:
                                await browser.switch_to_page(p["page"])
                                await paste_followup(p["page"], followup, "claude", label="Claude-retry-artifact")
                            except Exception as _e:
                                log(f"[Claude] Retry follow-up failed: {_e}", "WARN")
                            p["start_time"] = time.time() - (max_wait_min * 60) + (15 * 60)
                            p["done_count"] = 0
                            p["cua_confirmed"] = False
                            p["last_cua_check"] = time.time()
                            p.pop("_cached_text", None)
                            p["empty_retries"] = 0
                            continue
                        # wait_longer / timeout → extend budget ONCE; after the
                        # 2nd unanswered timeout, auto-skip instead of looping
                        # hard-fails forever.
                        p["hf_timeouts"] += 1
                        if p["hf_timeouts"] >= 2:
                            log(f"[Claude] 2-artifact hard-fail timed out {p['hf_timeouts']}× "
                                f"without a user decision — auto-skipping agent", "WARN")
                            _controls.skipped_agents.add(agent_key_hf)
                            continue
                        p["start_time"] = time.time() - (max_wait_min * 60) + (15 * 60)
                        p["done_count"] = 0
                        p["cua_confirmed"] = False
                        continue

                # 2026-04-25: CUA-confirmed done → run the same extract +
                # emit ladder used by the Playwright-confirmed path. Single
                # source of truth for save+emit (extract_and_record_agent),
                # no inline duplication. Empty extractions still revert to
                # polling (CUA likely misread completion).
                _queue_dir = (Path(__file__).parent / "queues" / _tracks_dir.name) \
                             if _tracks_dir else None
                res = await extract_and_record_agent(
                    name, p["page"], browser, cua_client,
                    queue_dir=_queue_dir, elapsed_sec=int(elapsed),
                    verbose=verbose,
                )
                if res["status"] == "done":
                    _runtime.unregister_page(name.lower().replace(" ", ""),
                                              final_status="done")
                    _runtime.agent_chat_urls[name.lower().replace(" ", "")] = res.get("url") or ""
                    results[name] = res
                    del pending[name]
                    log(f"[{name}] CUA-confirmed extraction complete — "
                        f"{len(res['text'])} chars, "
                        f"in_app={(res.get('_in_app_url') or '')[:60]}")
                    continue
                # Empty extraction → revert to polling. After 3 attempts, ask
                # the user (retry with follow-up / skip / stop). Same UX as
                # the previous inline empty-retries flow.
                p.setdefault("empty_retries", 0)
                p["empty_retries"] += 1
                if p["empty_retries"] < 3 and elapsed < (max_wait_min * 60 * 0.95):
                    log(f"[{name}] CUA said done but extraction empty "
                        f"(retry {p['empty_retries']}/3) — reverting to polling", "WARN")
                    p["done_count"] = 0
                    p["cua_confirmed"] = False
                    p["last_cua_check"] = time.time() + 60
                    emit_event("agent_progress", phase=2,
                               agent=name.lower().replace(" ", ""),
                               status="still_researching",
                               progress="Still working — extraction came back empty, retrying.",
                               elapsedSec=int(elapsed),
                               expectedMinutes=get_expected_minutes(2))
                    continue
                # 3 empty extractions — ask the user.
                ag_key_empty = name.lower().replace(" ", "")
                try:
                    emit_event("pipeline_warning", phase=2, agent=ag_key_empty,
                               message=f"{name} finished but no readable text was extracted",
                               details=("CUA says the agent is done, but 3 extraction attempts came "
                                        "back empty. Retry sends a follow-up asking for the complete "
                                        "report. Skip drops this agent and proceeds with the others."),
                               alertType="warn",
                               actions=[
                                   {"id": "retry", "label": "Retry", "style": "primary",
                                    "command": {"action": "retry_agent", "agent": ag_key_empty}},
                                   {"id": "skip", "label": "Skip", "style": "default",
                                    "command": {"action": "skip_agent", "agent": ag_key_empty}},
                               ])
                except Exception:
                    pass
                empty_decision = await _controls.await_agent_decision(ag_key_empty, timeout=300.0)
                log(f"[{name}] Empty-final user decision: {empty_decision}")
                if empty_decision == "stop":
                    break
                if empty_decision == "skip":
                    continue
                if empty_decision == "retry":
                    followup = (
                        "It looks like your final response didn't come through. Please output "
                        "the complete research report now — include all sources, sections, and findings. "
                        "No preamble or post-amble."
                    )
                    try:
                        emit_event("pipeline_warning", phase=2, agent=ag_key_empty,
                                   message=f"Retrying {name} — asking for the complete report",
                                   alertType="retrying")
                        await browser.switch_to_page(p["page"])
                        await paste_followup(p["page"], followup, name.lower(), label=f"{name}-retry-empty")
                    except Exception as e:
                        log(f"[{name}] Retry follow-up failed: {e}", "WARN")
                    p["start_time"] = time.time() - max(0, int(elapsed) - (15 * 60))
                    p["done_count"] = 0
                    p["cua_confirmed"] = False
                    p["last_cua_check"] = time.time()
                    p["empty_retries"] = 0
                    continue
                # timeout / continue_partial → fall through and accept the empty result.
                results[name] = {"status": "empty", "text": "",
                                 "url": p["page"].url if p["page"] else "",
                                 "page": p["page"], "elapsed_sec": int(elapsed)}
                _runtime.unregister_page(name.lower().replace(" ", ""), final_status="empty")
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
    """Extract ChatGPT response — CUA artifact copy (primary) → Playwright ENLARGE
    + DOM scrape (fallback) → JS innerText (last resort).
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

    # ── Step -1 (NEW, 2026-04-26 v3): close ANY open right-side panel ──
    # The activity/source panel kept open during polling occupies the same
    # right-side real estate as the canvas/document overlay. Without closing
    # it, ENLARGE click is captured by the source panel's z-index and the
    # canvas never mounts → CUA copies the wrong content (sources panel
    # preview, ~800-3000 chars, looks like a final report length-wise).
    # Try DOM close-X selectors first, then Escape as a fallback.
    try:
        closed = await page.evaluate("""() => {
            const sels = [
                'aside button[aria-label*="Close" i]',
                '[role="complementary"] button[aria-label*="Close" i]',
                '[class*="panel" i] button[aria-label*="Close" i]',
                '[class*="source" i] button[aria-label*="Close" i]',
                'aside button[aria-label*="close" i]',
            ];
            for (const s of sels) {
                try {
                    const b = document.querySelector(s);
                    if (b && (b.offsetWidth > 0 || b.offsetHeight > 0)) {
                        b.click();
                        return s;
                    }
                } catch (e) {}
            }
            return '';
        }""")
        if closed:
            log(f"[{label}] Closed source panel before ENLARGE via {closed}")
            await asyncio.sleep(0.6)
        else:
            # Blur composer first so Escape isn't swallowed by textarea focus.
            try:
                await page.evaluate(
                    "document.activeElement && document.activeElement.blur && document.activeElement.blur()")
            except Exception:
                pass
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
    except Exception:
        pass

    # ── Step 0 (NEW, 2026-04-26): EXPLICIT artifact-open via Playwright ──
    # Post-completion the DR artifact card is rendered but the FULL canvas/document
    # only mounts AFTER the user clicks ENLARGE/Open. Doing this BEFORE CUA means:
    #   (a) CUA's job becomes "just copy the open canvas" — much more reliable.
    #   (b) DOM/JS fallbacks (Method 3/4) below now have actual canvas content
    #       to scrape instead of the chat preamble.
    # Tries every selector variant we've seen + a text-content fallback that's
    # scoped to artifact/canvas/research ancestors so we don't accidentally click
    # an unrelated "Open Sidebar" button.
    try:
        opened = await page.evaluate("""() => {
            const selectors = [
                'button[aria-label*="Open the artifact" i]',
                'button[aria-label*="Open canvas" i]',
                'button[aria-label*="Enlarge" i]',
                'button[aria-label*="Expand" i]',
                'button[aria-label*="View artifact" i]',
                'button[data-testid*="artifact"]',
                'button[data-testid*="canvas"]',
                'a[href*="/canvas/"]',
                '[role="button"][aria-label*="Open" i]'
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && (el.offsetWidth > 0 || el.offsetHeight > 0)) {
                    el.click();
                    return { clicked: true, selector: sel };
                }
            }
            // Text-content fallback — scoped to artifact/canvas/research ancestors only
            for (const b of document.querySelectorAll('button, [role="button"]')) {
                const t = (b.textContent || '').trim().toLowerCase();
                if (t !== 'open' && t !== 'view' && t !== 'enlarge' && t !== 'expand') continue;
                const inArtifact = b.closest(
                    '[class*="artifact"], [class*="canvas"], [class*="research"], article'
                );
                if (inArtifact) {
                    b.click(); return { clicked: true, selector: 'text:'+t+'+scoped' };
                }
            }
            return { clicked: false };
        }""")
        if opened and opened.get("clicked"):
            log(f"[{label}] Post-completion: opened document artifact via Playwright "
                f"({opened.get('selector')}) — canvas mounting…")
            await asyncio.sleep(2.0)
        else:
            log(f"[{label}] Post-completion: no Playwright-clickable artifact-open button found "
                f"(CUA will try via PROMPT_COPY_ARTIFACT_CHATGPT)", "DEBUG")
    except Exception as _oe:
        log(f"[{label}] Post-completion artifact-open skipped: {_oe}", "DEBUG")

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

    # Method 2: HTML→MD from the now-opened canvas / artifact content block.
    # 2000-char gate (was 500): a 500-char preamble could pass; 2000 ensures we
    # have an actual report, not just the chat acknowledgement preamble.
    md = await _extract_html_to_md(page, [
        '.canvas-content', '.artifact-content', '[data-testid="canvas-content"]',
        '[role="dialog"] .markdown', '[role="dialog"] .prose',
        '[data-message-author-role="assistant"]:last-of-type .markdown',
    ], label)
    if md and len(md) > 2000:
        log(f"[{label}] Extracted via HTML→MD (canvas/artifact): {len(md)} chars")
        return md

    # Method 3: JS — last assistant message (regular chat mode, not Deep Research).
    # 2000-char gate same rationale as Method 2.
    try:
        text = await page.evaluate("""() => {
            // Prefer dialog-scoped content (open canvas) over chat preamble.
            const dlg = document.querySelector('[role="dialog"] .markdown, [role="dialog"] .prose');
            if (dlg && dlg.innerText && dlg.innerText.length > 2000) return dlg.innerText;
            const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
            if (msgs.length > 0) return msgs[msgs.length - 1].innerText;
            return '';
        }""")
        if text and len(text) > 2000:
            log(f"[{label}] Extracted via JS innerText: {len(text)} chars")
            return text
    except Exception:
        pass

    log(f"[{label}] All extraction methods failed (canvas may not have opened)", "WARN")
    return ""


async def extract_gemini_response(page, browser=None, cua_client=None, label="Gemini", verbose=False):
    """Dedicated Gemini extractor — HTML→MD → copy button → JS → clipboard.
    Each method emits an explicit log line so the path that succeeded (or
    the one that silently returned empty) is visible in the run log.
    Returns the markdown/text or "" on total failure."""
    await asyncio.sleep(2)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1)

    # Method 1: HTML → markdown from Gemini's response containers
    md = await _extract_html_to_md(page, [
        'message-content', '.model-response-text', '.response-container',
    ], label)
    if md and len(md) > 100:
        log(f"[{label}] Extracted via HTML→MD: {len(md)} chars")
        return md
    log(f"[{label}] HTML→MD returned {len(md or '')} chars — trying copy button", "WARN")

    # Method 2: click Gemini's built-in Copy button
    copied = await _try_copy_button(page, browser, cua_client, label, verbose)
    if copied and len(copied) > 100:
        log(f"[{label}] Extracted via copy button: {len(copied)} chars")
        return copied
    log(f"[{label}] Copy button returned {len(copied or '')} chars — trying JS", "WARN")

    # Method 3: innerText from response containers
    try:
        text = await page.evaluate("""() => {
            const r = document.querySelectorAll('message-content, .model-response-text, .response-container');
            if (r.length > 0) return r[r.length - 1].innerText;
            const turns = document.querySelectorAll('.conversation-turn');
            if (turns.length > 0) return turns[turns.length - 1].innerText;
            return '';
        }""")
        if text and len(text) > 100:
            log(f"[{label}] Extracted via JS innerText: {len(text)} chars")
            return text
        log(f"[{label}] JS innerText returned {len(text or '')} chars — trying select-all", "WARN")
    except Exception as _e:
        log(f"[{label}] JS innerText error: {_e}", "WARN")

    # Method 4: select-all + clipboard (last resort)
    log(f"[{label}] Falling back to select-all clipboard", "WARN")
    await page.keyboard.press("Control+a")
    await asyncio.sleep(0.5)
    await page.keyboard.press("Control+c")
    await asyncio.sleep(1)
    clip = get_clipboard() or ""
    if clip and len(clip) > 100:
        log(f"[{label}] Extracted via select-all clipboard: {len(clip)} chars")
    else:
        log(f"[{label}] All extraction methods failed — returning empty", "ERROR")
    return clip


async def extract_claude_response(page, browser=None, cua_client=None, label="Claude", verbose=False,
                                   artifact_panel_open=False):
    """Extract Claude response — artifact-aware extraction.
    Claude Deep Research produces 2 artifacts: first = intermediate tracking
    (kept open during polling for live source streaming), second = final report.
    Targets the LAST artifact for extraction, with multiple fallback methods.

    artifact_panel_open: poll-loop signal that artifact 1's panel is currently
    open (commit d45807f keeps it open across polls via keep_open=True). When
    True we explicitly CLOSE artifact-1 first so the subsequent LAST-card click
    definitely opens a fresh panel onto artifact-2 (final report) — without
    this, relying on a panel-swap can race or no-op (artifact_count==1 case)
    and silently extract artifact-1's references instead of the final report."""
    # Clear clipboard first so stale brief text doesn't get returned
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", "Set-Clipboard ''"],
                       capture_output=True, timeout=5)
    except Exception:
        pass
    await asyncio.sleep(2)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(1)

    # ── Step 0 (BROADENED 2026-04-26 v3): probe DOM directly, not just flag ──
    # Polling sets artifact_panel_open=True, but if extract is reached via a
    # different path (Phase-2 timeout, hard-retry recovery, manual continue) the
    # flag may be stale or False while the panel IS still visually open. Directly
    # probe the DOM for any visible side artifact panel (>200px wide). Close it
    # if present — without this, the LAST-card click silently opens the wrong
    # artifact (the still-foregrounded artifact-1 / sources checklist).
    panel_visible_dom = False
    try:
        panel_visible_dom = await page.evaluate("""() => {
            const sels = [
                'aside',
                '[class*="artifact-panel" i]',
                '[class*="side-panel" i]',
                '[role="complementary"]'
            ];
            for (const s of sels) {
                for (const el of document.querySelectorAll(s)) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 200 && r.height > 200) return true;
                }
            }
            return false;
        }""")
    except Exception:
        pass
    if panel_visible_dom or artifact_panel_open:
        log(f"[{label}] Closing artifact panel (visible_dom={panel_visible_dom}, "
            f"flag={artifact_panel_open}) before final extract")
        try:
            # Blur composer first so Escape isn't swallowed by textarea focus.
            try:
                await page.evaluate(
                    "document.activeElement && document.activeElement.blur && document.activeElement.blur()")
            except Exception:
                pass
            await _close_claude_artifact_panel(page)
            await asyncio.sleep(0.6)
        except Exception as _ce:
            log(f"[{label}] artifact-1 close before extract failed (continuing): {_ce}", "DEBUG")

    # ── Step 1: Count artifacts so we know which index = final report ──
    artifact_count = await _count_claude_artifacts(page)
    log(f"[{label}] Post-completion: found {artifact_count} artifact(s)")

    # ── Step 2 — EXPLICITLY open the LAST artifact card (= final report) ──
    # Method 1 (PRIMARY): DOM-click the LAST artifact card + read panel content.
    # The "LAST" artifact is the final research report. For 2-artifact runs this
    # is artifact-2 (after Step 0's close-1, panel is now closed → click opens
    # fresh onto artifact-2). For 1-artifact runs this is just the one artifact.
    if artifact_count > 0:
        target_idx = max(0, artifact_count - 1)  # Last artifact = final report
        log(f"[{label}] Post-completion: opening artifact[{target_idx}] (final report)")
        clicked = await _click_claude_artifact(page, index=target_idx)
        if clicked:
            await asyncio.sleep(2)  # Wait for panel render
            panel_text = await _read_claude_artifact_panel(page)
            if panel_text and len(panel_text) > 500:
                log(f"[{label}] Extracted via DOM artifact panel ({target_idx}): {len(panel_text)} chars")
                # Try to also get clipboard copy for higher fidelity
                try:
                    await page.evaluate("""() => {
                        const copyBtn = document.querySelector(
                            'aside button[aria-label*="Copy"], ' +
                            '[class*="artifact-panel"] button[aria-label*="Copy"], ' +
                            'button[data-testid="copy-artifact"]'
                        );
                        if (copyBtn) copyBtn.click();
                    }""")
                    await asyncio.sleep(1)
                    clipboard = get_clipboard()
                    if clipboard and len(clipboard) > len(panel_text) * 0.8:
                        log(f"[{label}] Upgraded to clipboard copy: {len(clipboard)} chars")
                        return clipboard
                except Exception:
                    pass
                return panel_text

    # Method 2: CUA opens the correct artifact and copies it
    if browser and cua_client:
        log(f"[{label}] CUA: Navigating to final artifact...")
        await browser.switch_to_page(page)
        # Use the new targeted prompt if 2+ artifacts, else original
        if artifact_count >= 2:
            await agent_loop(cua_client, browser, PROMPT_NAVIGATE_CLAUDE_FINAL_ARTIFACT,
                f"There are {artifact_count} artifacts in this conversation. "
                "Open the LAST (bottom) artifact — that's the final research report.",
                model=CUA_MODEL, max_iterations=8, verbose=verbose)
            await asyncio.sleep(1)
        await agent_loop(cua_client, browser, PROMPT_COPY_ARTIFACT_CLAUDE,
            "Copy the full content of the artifact currently open in the right panel to clipboard.",
            model=CUA_MODEL, max_iterations=12, verbose=verbose)
        await asyncio.sleep(1)
        clipboard = get_clipboard()
        if clipboard and len(clipboard) > 500:
            log(f"[{label}] Extracted via CUA artifact copy: {len(clipboard)} chars")
            return clipboard
        log(f"[{label}] CUA copy got {len(clipboard or '')} chars — trying fallbacks", "WARN")

    # Method 3: HTML→MD
    md = await _extract_html_to_md(page, [
        '[data-is-streaming="false"] .markdown', '.font-claude-message', '.contents .prose',
    ], label)
    if md and len(md) > 100:
        return md

    # Method 4: JS fallback
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

    log(f"[{label}] All extraction methods failed", "WARN")
    return ""


async def publish_open_claude_artifact(page, browser, cua_client, verbose=False):
    """Publish the currently-open Claude artifact and return its public URL.
    Call this AFTER extract_claude_response while the artifact panel is still open."""
    try:
        # Try DOM-first: click publish button on the artifact panel
        clicked = await page.evaluate("""() => {
            // Multiple selector strategies for the publish/share button
            const selectors = [
                'aside button[aria-label*="Publish"]',
                'aside button[aria-label*="Share"]',
                '[class*="artifact"] button[aria-label*="Publish"]',
                '[class*="artifact"] button[aria-label*="Share"]',
                'button[data-testid="publish-artifact"]',
                // Icon-based: globe or share icons in the artifact panel
                'aside button svg[class*="globe"]',
                'aside button svg[class*="share"]',
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el) {
                    const btn = el.closest('button') || el;
                    btn.click();
                    return 'clicked';
                }
            }
            return '';
        }""")
        if clicked == 'clicked':
            await asyncio.sleep(2)
            # Check if there's a "Publish" confirmation button in the dialog
            await page.evaluate("""() => {
                // Some versions show a confirmation dialog — click Publish/Confirm
                const btns = document.querySelectorAll('button, [role="button"]');
                for (const btn of btns) {
                    const txt = (btn.innerText || btn.textContent || '').toLowerCase().trim();
                    if (txt === 'publish' || txt === 'create public link' || txt === 'confirm') {
                        btn.click();
                        return 'confirmed';
                    }
                }
                return '';
            }""")
            await asyncio.sleep(2)
            # Look for the URL in the dialog (try multiple times — UI may be animating)
            for _attempt in range(3):
                url = await page.evaluate("""() => {
                    // Check for direct links
                    const links = document.querySelectorAll(
                        'a[href*="claude.site/artifacts"], input[value*="claude.site"]'
                    );
                    for (const el of links) {
                        const href = el.href || el.value || '';
                        if (href.includes('claude.site')) return href;
                    }
                    // Check visible text for claude.site URL
                    const text = document.body.innerText;
                    const m = text.match(/https:\\/\\/claude\\.site\\/artifacts\\/[a-f0-9-]+/);
                    if (m) return m[0];
                    return '';
                }""")
                if url and url.startswith('http') and 'claude.site' in url:
                    log(f"[Claude] Published artifact via DOM: {url}")
                    return url
                # Try clicking "Copy link" button
                copy_result = await page.evaluate("""() => {
                    const btns = document.querySelectorAll('button');
                    for (const b of btns) {
                        const txt = (b.innerText || '').toLowerCase();
                        if (txt.includes('copy link') || txt.includes('copy url')) {
                            b.click();
                            return 'copied';
                        }
                    }
                    return '';
                }""")
                if copy_result == 'copied':
                    await asyncio.sleep(0.5)
                    clip = get_clipboard()
                    if clip and 'claude.site' in clip:
                        log(f"[Claude] Published artifact via clipboard: {clip}")
                        return clip
                await asyncio.sleep(1)
    except Exception as e:
        log(f"[Claude] DOM publish attempt failed: {e}", "WARN")

    # CUA fallback for publishing
    if cua_client:
        result = await agent_loop(cua_client, browser,
            PROMPT_PUBLISH_CLAUDE_ARTIFACT,
            "Publish the artifact that's currently open in the right panel. "
            "Click the Publish/Share button, then confirm publishing. "
            "Get the public URL (claude.site/artifacts/...). Tell me the EXACT URL.",
            model=CUA_MODEL, max_iterations=10, verbose=verbose)
        text = result.get("text", "")
        m = re.search(r'https://claude\.site/artifacts/[a-f0-9-]+', text)
        if not m:
            m = re.search(r'https://claude\.(?:site|ai)/[^\s]+', text)
        if m:
            return m.group(0)
        clip = get_clipboard()
        if clip and 'claude.site' in clip:
            return clip

    return ""


# ── Phase 1: Research Brief Generation ───────────────────────────────────────

async def run_phase1(browser, cua_client, topic, pdf_paths, verbose=False, feedback="", _retry_count=0):
    """Phase 1: ChatGPT Pro + Extended Thinking → research brief.

    _retry_count: internal counter bounded to P1_MAX_USER_RETRIES. Incremented
    when the brief-short branch restarts Phase 1 at the user's request. Caps
    total attempts to avoid infinite loops."""
    log("=" * 60)
    log("PHASE 1: Research Brief Generation (ChatGPT Pro + Extended Thinking)")
    log("=" * 60)

    # Navigate to ChatGPT
    emit_event("agent_progress", phase=1, agent="chatgpt",
               status="starting",
               progress="Opening ChatGPT…")
    await browser.navigate("https://chatgpt.com")
    await asyncio.sleep(3)

    # Inject MutationObserver early — right after navigate, before HV check.
    # The scrape selector (`[data-message-author-role="assistant"]`) doesn't
    # exist on HV/login pages, so early-inject produces no false positives
    # and captures any brief streaming that starts before `verify-generating`
    # closes. `inject_agent_observer` is idempotent on re-call.
    try:
        await inject_agent_observer(browser.page, "chatgpt")
    except Exception:
        pass

    # Early HV check — if Cloudflare Turnstile / CAPTCHA is gating ChatGPT,
    # resolve it BEFORE running Pro-model selection. Those CUA calls can't
    # succeed on a blocked page and will burn workspace quota for nothing.
    # On clear-failure, return None so the pipeline runner emits
    # pipeline_error + pipeline_stopped via fail_phase(...) downstream.
    if cua_client:
        emit_event("agent_progress", phase=1, agent="chatgpt",
                   status="verifying",
                   progress="Checking for CAPTCHA / human-verification gate…")
        cleared = await check_hv_gate(browser, cua_client, "chatgpt", "ChatGPT",
                                       phase=1, verbose=verbose)
        if not cleared:
            log("Phase 1: HV gate could not be cleared — aborting phase", "ERROR")
            return None

    # Select Pro model via CUA. Hard 180s ceiling — max_iterations=15 is
    # generous enough that a stuck CUA could loiter for many minutes
    # without this wait_for. If timed out, log + assume Pro is unavailable
    # so the rest of Phase 1 falls through gracefully (the pipeline still
    # gets an Extended Thinking attempt without the Pro model upgrade).
    if cua_client:
        log("Selecting Pro + Extended Thinking...")
        emit_event("agent_progress", phase=1, agent="chatgpt",
                   status="selecting_model",
                   progress="Selecting ChatGPT Pro with Extended Thinking…")
        try:
            result = await asyncio.wait_for(
                agent_loop(cua_client, browser, PROMPT_SELECT_PRO,
                    "Select ChatGPT Pro model with Extended Thinking. Say 'no pro available' if not found.",
                    model=CUA_MODEL, max_iterations=15, verbose=verbose),
                timeout=180.0,
            )
        except asyncio.TimeoutError:
            log("Phase 1: Pro+Extended Thinking selection timed out (180s) — proceeding without explicit Pro upgrade", "WARN")
            result = {"text": "no pro available (cua_timeout)"}
        last = (result.get("text") or "").lower()
        if "no pro" in last or "not available" in last:
            log("Pro mode not available", "WARN")

    # Attach PDFs
    _pdf_total = len(pdf_paths) if pdf_paths else 0
    for _pdf_idx, pdf in enumerate(pdf_paths, 1):
        _pdf_name = Path(pdf).name
        log(f"Attaching PDF: {_pdf_name}")
        _pdf_progress = (f"Attaching {_pdf_name} ({_pdf_idx}/{_pdf_total})…"
                         if _pdf_total > 1 else f"Attaching {_pdf_name}…")
        emit_event("agent_progress", phase=1, agent="chatgpt",
                   status="attaching_pdf",
                   progress=_pdf_progress)
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
    emit_event("agent_progress", phase=1, agent="chatgpt",
               status="submitting",
               progress="Submitting the research-brief prompt…")
    submitted = await submit_chatgpt_direct(browser, prompt)
    if not submitted and cua_client:
        log("Falling back to CUA for submit...")
        await agent_loop(cua_client, browser, PROMPT_SUBMIT_FALLBACK,
            f"Submit this prompt to ChatGPT:\n\n{prompt}",
            model=CUA_MODEL, max_iterations=15, verbose=verbose)

    # VERIFY: confirm ChatGPT is generating
    emit_event("agent_progress", phase=1, agent="chatgpt",
               status="verifying_generation",
               progress="Waiting for ChatGPT Pro + Thinking to start generating…")
    verified = await wait_until_verified(verify_chatgpt_generating, browser.page, "Phase1",
        browser=browser, cua_client=cua_client, max_retries=15, interval=3, verbose=verbose)
    if not verified:
        log("Phase 1: Could not verify ChatGPT is generating", "ERROR")
        # Most common cause: ChatGPT threw a "Something went wrong" banner
        # mid-submission or the Pro+Thinking model hit an internal error.
        # Surface a clear message so the user knows it wasn't a silent hang.
        try:
            emit_event("pipeline_warning", phase=1, agent="chatgpt",
                       message="ChatGPT didn't start generating the brief",
                       details="After submit, no streaming response was detected. Most likely ChatGPT's Pro + Thinking model threw an error or the Send click didn't land. The orchestrator will retry up to 2 more times.",
                       alertType="warn")
        except Exception:
            pass
        return None

    # Register brief page with dispatcher for mid-run user input.
    # MutationObserver was already injected earlier (right after navigate) so
    # the observer has been capturing token-level stream during verify.
    _runtime.phase = 1
    _runtime.sub_state = "1_brief_generating"
    _runtime.register_page("chatgpt", browser.page, browser.page.url)

    # Wait for response
    log(f"Polling for response (every {POLL_PRO}s, max {MAX_WAIT_PRO}min)...")
    completed = await poll_until_done(browser.page, verify_chatgpt_generating, "Phase1", POLL_PRO, MAX_WAIT_PRO,
        browser=browser, cua_client=cua_client, verbose=verbose, phase=1)
    # Unregister once brief is done
    _runtime.unregister_page("chatgpt", final_status="done" if completed else "timeout")
    # If the poll timed out (45 min default), tell the user we're still
    # going to try extracting whatever streamed so far rather than trash
    # the phase. The brief-short check below handles the "partial / empty"
    # case; this emit just explains the timeout.
    if not completed:
        retries_left_p1t = max(0, 2 - _retry_count)
        p1t_actions = []
        if retries_left_p1t > 0:
            p1t_actions.append({
                "id": "retry", "label": f"Retry brief ({retries_left_p1t} left)",
                "style": "primary",
                "command": {"action": "retry_phase", "phase": 1},
            })
        p1t_actions.append({
            "id": "continue_anyway", "label": "Continue with partial",
            "style": "default" if retries_left_p1t > 0 else "primary",
            "command": {"action": "continue_anyway"},
        })
        try:
            emit_event("pipeline_warning", phase=1, agent="chatgpt",
                       message=f"Brief generation timed out after {MAX_WAIT_PRO} min",
                       details=f"ChatGPT's Pro + Thinking model was still running at the {MAX_WAIT_PRO}-minute cap. Retry re-submits a fresh brief request. Continue with partial extracts whatever text streamed so far and proceeds to Phase 2.",
                       alertType="warn",
                       actions=p1t_actions)
        except Exception:
            pass
        if retries_left_p1t > 0:
            p1t_decision = await _controls.await_retry_or_continue(phase=1, timeout=600.0)
            log(f"Phase 1 brief-timeout decision: {p1t_decision}")
            if p1t_decision == "stop":
                return None
            if p1t_decision == "retry":
                try:
                    emit_event("phase_restart", phase=1,
                               reason="user_retry_brief_timeout",
                               attempt=_retry_count + 2)
                except Exception:
                    pass
                _runtime.unregister_page("chatgpt", final_status="timeout-retrying")
                return await run_phase1(browser, cua_client, topic, pdf_paths,
                                        verbose=verbose, feedback=feedback,
                                        _retry_count=_retry_count + 1)
            # continue_anyway / timeout → fall through and extract partial

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

    brief_len = len(brief_text or "")
    # Brief-short guard: DR briefs are typically 2-5k chars. Under 500 while
    # we were expecting >1000 usually means ChatGPT errored or the extractor
    # grabbed the wrong element. Warn (not error) so the frontend can offer
    # [continue_anyway] / [retry] — the caller polls consume_continue_anyway()
    # to decide whether to accept the short brief.
    P1_MAX_USER_RETRIES = 2  # total attempts = 1 + P1_MAX_USER_RETRIES
    if brief_text and brief_len >= 100 and brief_len < 500:
        retries_left = max(0, P1_MAX_USER_RETRIES - _retry_count)
        retry_label = f"Retry Phase 1 ({retries_left} left)" if retries_left > 0 else None
        actions = []
        if retries_left > 0:
            actions.append({"id": "retry", "label": retry_label,
                            "style": "primary",
                            "command": {"action": "retry_phase", "phase": 1}})
        actions.append({"id": "continue_anyway", "label": "Continue anyway",
                        "style": "default" if retries_left > 0 else "primary",
                        "command": {"action": "continue_anyway"}})
        try:
            emit_event("pipeline_warning", phase=1, agent="chatgpt",
                       message=f"Brief looks short ({brief_len} chars) — expected >1000",
                       details="ChatGPT returned a brief well below typical length. Retry regenerates the brief from scratch — Phase 2 waits until the new brief is ready, then runs with the better version. Continue anyway uses what we have.",
                       alertType="warn",
                       actions=actions)
        except Exception:
            pass
        # Wait for the user's decision. 10 min window — if they ignore the
        # banner we default to continuing with the short brief rather than
        # hanging the pipeline indefinitely.
        if retries_left > 0:
            decision = await _controls.await_retry_or_continue(phase=1, timeout=600.0)
            log(f"Phase 1 brief-short decision: {decision}")
            if decision == "stop":
                return None
            if decision == "retry":
                try:
                    emit_event("phase_restart", phase=1,
                               reason="user_retry_brief_short",
                               attempt=_retry_count + 2,
                               chars=brief_len)
                except Exception:
                    pass
                log(f"Phase 1: User requested retry (attempt {_retry_count + 2}/{P1_MAX_USER_RETRIES + 1})")
                return await run_phase1(browser, cua_client, topic, pdf_paths,
                                        verbose=verbose, feedback=feedback,
                                        _retry_count=_retry_count + 1)
            # 'continue_anyway' or 'timeout' → fall through and return short brief

    if brief_text and brief_len > 100:
        log(f"Brief extracted: {brief_len} chars")
        return {"text": brief_text, "url": chat_url}
    else:
        log(f"Brief too short ({brief_len} chars)", "WARN")
        return {"text": brief_text or "", "url": chat_url}


# ── Phase 2: Parallel Deep Research (Sequential Start + Verify) ──────────────

# ── Playwright-direct platform setup (replaces vision-based CUA setup) ────────

async def setup_chatgpt_dr(page) -> bool:
    """Enable ChatGPT Deep Research mode via direct selectors. Returns True on success.

    Step-by-step logs emit on every branch so next run's log tells us
    exactly which step broke — previously this was one-line "setup failed"
    with no detail, leaving us guessing whether the + menu opened, whether
    the DR option was found, or whether verification landed.
    """
    try:
        await asyncio.sleep(2)
        # Step 1: open the + / tools menu in the composer
        menu_sel = None
        for sel in ['button[aria-label*="Use a tool"]',
                    'button[aria-label*="Attach"]',
                    'button[data-testid="composer-plus-btn"]',
                    'button[aria-label*="More"]']:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(0.8)
                    menu_sel = sel
                    break
            except Exception:
                continue
        if not menu_sel:
            log("[setup_chatgpt_dr] Step 1 FAIL: tools/+ menu button not found — selectors may have rotated", "WARN")
            return False
        log(f"[setup_chatgpt_dr] Step 1 OK: opened tools menu via {menu_sel}")

        # Step 2: click "Deep research" option in the menu
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
            log("[setup_chatgpt_dr] Step 2 FAIL: 'Deep research' menu item not found — menu opened but option missing", "WARN")
            return False
        log("[setup_chatgpt_dr] Step 2 OK: clicked Deep research menu option")
        await asyncio.sleep(1.5)

        # Step 3: verify DR actually activated — look for the DR pill in the
        # composer area (not anywhere in body text, which was the previous
        # false-positive-prone check that matched tooltips and help labels).
        active = await page.evaluate("""() => {
            const composer = document.querySelector('form') || document.body;
            // Prefer a visible pill/chip inside the composer
            const chips = [...composer.querySelectorAll('button, [role="button"], span, div')];
            for (const el of chips) {
                if (!el.offsetParent) continue;
                const t = (el.textContent || '').trim().toLowerCase();
                if (t === 'deep research' || t === 'deep research off') {
                    // Composer-level visible pill is the active-mode indicator
                    return { ok: true, via: 'pill', text: el.textContent.trim().slice(0, 40) };
                }
            }
            // Secondary signal: composer placeholder changes for DR mode
            const ta = document.querySelector('#prompt-textarea, textarea, [contenteditable="true"]');
            if (ta) {
                const placeholder = (ta.getAttribute('placeholder') || ta.getAttribute('data-placeholder') || '').toLowerCase();
                if (placeholder.includes('research')) {
                    return { ok: true, via: 'placeholder', text: placeholder.slice(0, 60) };
                }
            }
            return { ok: false };
        }""")
        if not active or not active.get("ok"):
            log("[setup_chatgpt_dr] Step 3 FAIL: clicked DR but no pill/placeholder change visible after 1.5s — click may have been intercepted", "WARN")
            return False
        log(f"[setup_chatgpt_dr] Step 3 OK: verified DR active via {active.get('via')} → {active.get('text')}")
        return True
    except Exception as e:
        log(f"[setup_chatgpt_dr] exception: {e}", "WARN")
        return False


async def setup_gemini_dr(page) -> bool:
    """Enable Gemini Deep Research pill via direct selectors. Returns True on success.

    Step-by-step logs emit on every branch so next run's log tells us
    whether the pill was missing, the model-dropdown fallback fired, or
    verification couldn't find the active pill afterwards.
    """
    try:
        await asyncio.sleep(2)

        # Step 1: try the direct Deep Research pill/button in the composer
        direct_clicked = await page.evaluate("""() => {
            const candidates = document.querySelectorAll('button, [role="button"], [role="menuitem"]');
            for (const b of candidates) {
                if (!b.offsetParent) continue;
                const t = (b.textContent || '').trim().toLowerCase();
                const a = (b.getAttribute('aria-label') || '').toLowerCase();
                if (t === 'deep research' || a === 'deep research' || t.startsWith('deep research')) {
                    b.click();
                    return true;
                }
            }
            return false;
        }""")
        if direct_clicked:
            log("[setup_gemini_dr] Step 1 OK: clicked DR pill directly in composer")
        else:
            log("[setup_gemini_dr] Step 1: DR pill not directly visible — trying model-dropdown fallback", "INFO")

        # Step 2 (fallback): DR may live inside the model/tools dropdown
        if not direct_clicked:
            for sel in ['button[aria-label*="model"]', 'button[data-test-id*="model"]']:
                try:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        await asyncio.sleep(0.8)
                        log(f"[setup_gemini_dr] Step 2: opened {sel}")
                        direct_clicked = await page.evaluate("""() => {
                            const items = document.querySelectorAll('[role="menuitem"], [role="option"], button');
                            for (const el of items) {
                                const t = (el.textContent || '').trim().toLowerCase();
                                if (t.includes('deep research')) { el.click(); return true; }
                            }
                            return false;
                        }""")
                        if direct_clicked:
                            log(f"[setup_gemini_dr] Step 2 OK: DR selected via {sel} dropdown")
                            break
                        else:
                            log(f"[setup_gemini_dr] Step 2 {sel}: dropdown opened but DR option absent", "WARN")
                except Exception as e:
                    log(f"[setup_gemini_dr] Step 2 {sel} errored: {e}", "WARN")
                    continue

        if not direct_clicked:
            log("[setup_gemini_dr] FAIL: neither direct pill nor dropdown fallback landed DR — selectors likely rotated", "WARN")
            return False

        await asyncio.sleep(1.5)

        # Step 3: verify the pill is visible AND reads as active (not just
        # a hover tooltip or inactive label). Gemini exposes the active
        # state via aria-pressed / aria-selected on its chip buttons.
        active = await page.evaluate("""() => {
            const pills = document.querySelectorAll('button, [role="button"]');
            for (const p of pills) {
                if (!p.offsetParent) continue;
                const t = (p.textContent || '').trim().toLowerCase();
                if (t !== 'deep research') continue;
                const pressed = p.getAttribute('aria-pressed') === 'true' ||
                                 p.getAttribute('aria-selected') === 'true' ||
                                 (p.className || '').toLowerCase().includes('active') ||
                                 (p.className || '').toLowerCase().includes('selected');
                return { ok: true, pressed, text: p.textContent.trim().slice(0, 40) };
            }
            return { ok: false };
        }""")
        if not active or not active.get("ok"):
            log("[setup_gemini_dr] Step 3 FAIL: DR pill not visible after click — UI may not have reflected the selection", "WARN")
            return False
        if not active.get("pressed"):
            log(f"[setup_gemini_dr] Step 3 WARN: DR pill visible but no active-state attribute ({active.get('text')}) — proceeding but may be in off state")
        else:
            log(f"[setup_gemini_dr] Step 3 OK: DR pill active → {active.get('text')}")
        return True
    except Exception as e:
        log(f"[setup_gemini_dr] exception: {e}", "WARN")
        return False


async def setup_claude_dr(page) -> bool:
    """Enable Claude Opus 4.7 + Adaptive Thinking + Research tool via
    direct Playwright selectors. These are THREE independent controls in
    the current Claude.ai UI:
        1. Model dropdown        → Opus 4.7
        2. Adaptive Thinking     → on (separate toggle/pill, often next to the model name)
        3. Research tool         → on (inside the "+" tools menu)
    The CUA fallback lives one layer up in setup_agent so this routine can
    hard-return False the moment any step fails, without fighting the DOM."""
    try:
        await asyncio.sleep(2)

        # ── Step 1: open model dropdown and pick Opus 4.7 ─────────────
        dropdown_clicked = await page.evaluate("""() => {
            const btns = [...document.querySelectorAll('button')].filter(b => b.offsetParent !== null);
            // Model selector button shows the currently-selected model name.
            // Priority: already-Opus > Sonnet > any button with "claude"
            let dropdown = btns.find(b => (b.textContent || '').toLowerCase().includes('opus'));
            if (!dropdown) dropdown = btns.find(b => {
                const t = (b.textContent || '').toLowerCase();
                return t.includes('sonnet') || t.includes('haiku') || t.includes('claude');
            });
            if (dropdown) { dropdown.click(); return true; }
            return false;
        }""")
        if dropdown_clicked:
            log("[setup_claude_dr] Step 1A OK: opened model dropdown")
            await asyncio.sleep(0.8)
            opus_selected = await page.evaluate("""() => {
                const items = [...document.querySelectorAll('[role="menuitem"], [role="option"], button, a, li')];
                // Priority 1: exact "Opus 4.7"
                let pick = items.find(el => {
                    const t = (el.textContent || '').trim().toLowerCase();
                    return t.includes('opus') && t.includes('4.7');
                });
                // Priority 2: any Opus 4.x variant (future-proof)
                if (!pick) pick = items.find(el => {
                    const t = (el.textContent || '').trim().toLowerCase();
                    return t.includes('opus') && t.includes('4');
                });
                // Priority 3: any Opus at all
                if (!pick) pick = items.find(el => (el.textContent || '').toLowerCase().includes('opus'));
                if (pick) { pick.click(); return pick.textContent.trim(); }
                return null;
            }""")
            if opus_selected:
                log(f"[setup_claude_dr] Step 1B OK: selected {opus_selected}")
            else:
                log("[setup_claude_dr] Step 1B FAIL: Opus 4.7 option not in dropdown — rollout or A/B difference?", "WARN")
                return False
            await asyncio.sleep(0.6)
            # Dismiss the dropdown so the Adaptive Thinking toggle is clickable
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.3)
            except Exception:
                pass
        else:
            log("[setup_claude_dr] Step 1A FAIL: model dropdown button not found — selector list likely stale", "WARN")
            return False

        # ── Step 2: toggle Adaptive Thinking ON ────────────────────────
        # The toggle is a separate control — usually a pill/switch near
        # the model name or inside a "Thinking" submenu. State-aware:
        # only click when not already on. "Extended Thinking" as a label
        # no longer exists on current Claude.ai (was renamed to Adaptive
        # Thinking) — matching it risks clicking a stale/cached pill on
        # a partially-loaded page, so that fallback is intentionally gone.
        adaptive_state = await page.evaluate("""() => {
            const els = [...document.querySelectorAll(
                'button, [role="switch"], [role="checkbox"], [role="menuitem"], [role="option"], label'
            )].filter(el => el.offsetParent !== null);
            const matches = els.filter(el => {
                const t = (el.textContent || '').trim().toLowerCase();
                const a = (el.getAttribute('aria-label') || '').toLowerCase();
                return t === 'adaptive thinking' ||
                       a === 'adaptive thinking' ||
                       t.startsWith('adaptive thinking') ||
                       a.startsWith('adaptive thinking');
            });
            if (!matches.length) return { found: false };
            const el = matches[0];
            const checked = el.getAttribute('aria-checked') === 'true' ||
                             el.getAttribute('aria-pressed') === 'true' ||
                             el.dataset.state === 'checked' || el.dataset.state === 'on';
            if (!checked) { el.click(); return { found: true, toggled: true, label: el.textContent.trim() }; }
            return { found: true, toggled: false, label: el.textContent.trim() };
        }""")
        if not adaptive_state.get("found"):
            log("[setup_claude_dr] Step 2 WARN: Adaptive Thinking toggle not found — UI may have shipped under a new label", "WARN")
        else:
            log(f"[setup_claude_dr] Step 2 OK: Adaptive Thinking {'just enabled' if adaptive_state.get('toggled') else 'already on'} "
                f"(label='{adaptive_state.get('label')}')")
        await asyncio.sleep(0.4)

        # ── Step 3: open tools menu and enable Research ────────────────
        # Precise selectors first — the old `button[aria-label*="+"]`
        # wildcard was matching unrelated buttons ("New chat", etc.)
        # and occasionally opened the wrong surface.
        tools_opened = False
        tools_sel_used = None
        for sel in ['button[aria-label="Open tools menu"]',
                    'button[aria-label*="tools menu"]',
                    'button[aria-label*="Tools menu"]',
                    'button[data-testid*="tools"]',
                    'button[aria-label*="attach"]',
                    'button[aria-haspopup="menu"][aria-label*="tools"]']:
            try:
                btn = await page.query_selector(sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(0.6)
                    tools_opened = True
                    tools_sel_used = sel
                    break
            except Exception:
                continue
        if tools_opened:
            log(f"[setup_claude_dr] Step 3A OK: opened tools menu via {tools_sel_used}")
        else:
            log("[setup_claude_dr] Step 3A FAIL: tools menu button not found — aria-labels rotated or language changed", "WARN")
        research_enabled = False
        if tools_opened:
            # State-aware + accept label variations ("Research", "Research
            # tool", "Deep research"). Only clicks when not already on.
            research_enabled = await page.evaluate("""() => {
                const items = [...document.querySelectorAll(
                    '[role="menuitem"], button, [role="switch"], [role="checkbox"], label'
                )].filter(el => el.offsetParent !== null);
                const target = items.find(el => {
                    const t = (el.textContent || '').trim().toLowerCase();
                    const a = (el.getAttribute('aria-label') || '').toLowerCase();
                    return t === 'research' || a === 'research' ||
                           t === 'research tool' || a === 'research tool' ||
                           t === 'deep research' || a === 'deep research' ||
                           t.startsWith('research ') || a.startsWith('research ');
                });
                if (!target) return false;
                const checked = target.getAttribute('aria-checked') === 'true' ||
                                 target.getAttribute('aria-pressed') === 'true' ||
                                 target.dataset.state === 'checked' || target.dataset.state === 'on';
                if (!checked) target.click();
                return true;
            }""")
            await asyncio.sleep(0.4)
            try:
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.3)
            except Exception:
                pass
        if research_enabled:
            log("[setup_claude_dr] Step 3B OK: Research tool toggled on")
        else:
            log("[setup_claude_dr] Step 3B FAIL: Research tool item not found in tools menu — will run in chat mode, NOT research", "WARN")

        # Focus the input so the brief paste/attach lands cleanly.
        for sel in ['div[contenteditable="true"]', '[aria-label*="message"]', '.ProseMirror']:
            try:
                inp = await page.query_selector(sel)
                if inp:
                    await inp.click()
                    break
            except Exception:
                continue
        # Success only when all three critical knobs are in place
        return bool(opus_selected) and bool(research_enabled)
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
        "claude": "Verify Opus 4.7 Adaptive + Research tool are ON in Claude. Clear any stale attachments. Do not type.",
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


async def detect_human_verification(page, platform: str, label: str) -> tuple[bool, str]:
    """Detect if the current page is blocked by a human-verification challenge.

    Looks for the most common gates Claude / ChatGPT / Gemini use when they
    flag the automated browser:
      - Cloudflare Turnstile ("Just a moment..." / iframe[src*=challenges])
      - Generic CAPTCHA iframes (reCAPTCHA, hCaptcha)
      - Claude's own "Verify you are human" interstitial
      - Anthropic's "Checking your browser" intermediate page

    Returns (blocked, reason). `reason` is a short, user-readable string like
    "Cloudflare challenge" or "reCAPTCHA" — safe to surface in a chat banner.

    Never raises — on any detection error, returns (False, "").
    """
    try:
        result = await page.evaluate("""() => {
            const findings = [];
            const text = (document.body?.innerText || '').toLowerCase();

            // Cloudflare Turnstile / "Just a moment..."
            if (document.querySelector('iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"], .cf-turnstile, .cf-challenge')) {
                findings.push('Cloudflare');
            }
            if (text.includes('just a moment') && text.includes('cloudflare')) {
                findings.push('Cloudflare');
            }
            if (text.includes('checking your browser') || text.includes('checking if the site connection is secure')) {
                findings.push('Cloudflare');
            }

            // Google reCAPTCHA
            if (document.querySelector('iframe[src*="recaptcha"], .g-recaptcha, #recaptcha')) {
                findings.push('reCAPTCHA');
            }

            // hCaptcha
            if (document.querySelector('iframe[src*="hcaptcha"], .h-captcha')) {
                findings.push('hCaptcha');
            }

            // Claude / Anthropic human-verification interstitials
            if (text.includes('verify you are human') || text.includes('are you a human') ||
                text.includes('please complete the security check') ||
                text.includes('press and hold') || text.includes('tap and hold')) {
                findings.push('Claude human verification');
            }

            // Generic "blocked" / access-denied pages that we should surface
            if (text.includes('access denied') && text.length < 1000) {
                findings.push('Access denied');
            }

            return { findings: [...new Set(findings)] };
        }""")
        findings = result.get("findings", []) if isinstance(result, dict) else []
        if findings:
            return True, findings[0]
        return False, ""
    except Exception as e:
        log(f"[{label}] human-verification detect error: {e}", "WARN")
        return False, ""


async def detect_session_expiry(page, platform: str, label: str) -> tuple[bool, str]:
    """Detect if an agent page has lost its session mid-run (redirect to
    login URL, login form appeared, or "sign in to continue" message).

    Distinct from detect_human_verification — that handles CAPTCHA / Cloudflare.
    This handles actual logged-out state where the user needs to re-authenticate
    on their PC before the pipeline can resume.

    Returns (expired, reason). Never raises."""
    try:
        url = (page.url or "").lower()
        # URL markers for known login routes per platform
        url_markers = {
            "chatgpt":    ("/auth/login", "/auth/signin", "auth.openai.com"),
            "gemini":     ("accounts.google.com/signin", "accounts.google.com/serviceLogin"),
            "claude":     ("/login", "/sign-in", "/auth/"),
            "notebooklm": ("accounts.google.com/signin", "accounts.google.com/serviceLogin"),
        }
        markers = url_markers.get(platform.lower(), ("/login", "/signin", "/signup"))
        if any(m in url for m in markers):
            return True, f"redirect_to_login_url"

        # DOM markers: visible password field + no active chat UI
        result = await page.evaluate("""() => {
            const pwInput = document.querySelector('input[type="password"]:not([style*="display: none"])');
            if (!pwInput) return { expired: false };
            // Heuristic: if there's a visible password input AND no chat composer/send button,
            // we're on a login page. Use offsetParent check to filter hidden elements.
            if (pwInput.offsetParent === null) return { expired: false };
            const hasComposer = document.querySelector(
                '[data-testid="send-button"], button[aria-label*="Send prompt"], ' +
                'div[contenteditable="true"]#prompt-textarea, ' +
                'textarea[placeholder*="Message"], [data-test-id="send-button"]'
            );
            if (hasComposer) return { expired: false };
            const text = (document.body.innerText || '').toLowerCase();
            const loginPhrases = ['sign in to', 'log in to', 'please sign in',
                'welcome back', 'enter your password', 'email address'];
            const hasLoginText = loginPhrases.some(p => text.includes(p));
            return { expired: hasLoginText };
        }""")
        if isinstance(result, dict) and result.get("expired"):
            return True, "login_form_appeared"
        return False, ""
    except Exception as e:
        log(f"[{label}] session-expiry detect error: {e}", "WARN")
        return False, ""


async def _playwright_hv_click(page, label: str) -> bool:
    """Cheap DOM-based HV click. Returns True iff we actually clicked
    something. No budget for image-puzzles — those fall through to CUA.

    NEVER-DIE-MIGRATION-2026-04-18: Tier 0 of the HV chain. Cloudflare
    Turnstile is cross-origin-iframe'd so we can't touch its DOM, but we
    can mouse.click at the checkbox's known position inside the iframe.
    For in-page 'Verify you are human' / 'Continue' buttons, plain
    locator clicks work."""
    # Cloudflare Turnstile — checkbox inside a cross-origin iframe.
    try:
        cf = page.locator(
            'iframe[src*="challenges.cloudflare.com"], iframe[src*="turnstile"]'
        ).first
        if await cf.count() > 0:
            box = await cf.bounding_box()
            if box:
                # The checkbox sits ~30px in from the iframe's left edge,
                # vertically centered. Cross-origin body is unreachable
                # but mouse events at page coordinates land inside it.
                cx = box["x"] + 30
                cy = box["y"] + box["height"] / 2
                await page.mouse.click(cx, cy)
                log(f"[{label}] Playwright: clicked Turnstile checkbox at ({cx:.0f},{cy:.0f})")
                return True
    except Exception as e:
        log(f"[{label}] Playwright Turnstile click errored: {e}", "WARN")
    # In-page 'Verify you are human' / 'Continue' / 'I am human' buttons.
    for sel in (
        'button:has-text("Verify you are human")',
        'button:has-text("I am human")',
        'button:has-text("I\'m human")',
        'button:has-text("Continue")',
    ):
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click(timeout=3000)
                log(f"[{label}] Playwright: clicked '{sel}'")
                return True
        except Exception:
            continue
    return False


async def wait_for_verification_clearance(browser, cua_client, page, platform: str, label: str,
                                          verbose=False, max_wait_loops: int = 120,
                                          phase: int = 2) -> bool:
    """Handle a human-verification gate on an agent page.

    Flow (NEVER-DIE-MIGRATION-2026-04-18, full HV chain):
      0. Playwright cheap-click — cross-origin iframe click on the
         Turnstile checkbox, or in-page 'Verify you are human' button.
         Zero CUA budget; most Cloudflare checkboxes clear here.
      1. CUA in-place (3 iter) — vision click for whatever Playwright
         missed. Silent on success.
      2. 3-minute cooldown + page reload — lets Cloudflare's bot score
         decay, re-runs stealth init against a fresh document.
      3. CUA retry (5 iter) — second pass on the reloaded page.
      4. Kill-tab — close the page, open a fresh tab at the same URL.
         A new cookie jar + clean document sometimes clears a stuck
         session that the reload alone couldn't.
      5. User pause — human_verification_required alert with
         Resume / Skip agent. Polls every 5s so a manual solve auto-
         resumes even if the user never taps Resume.

    `phase` parameter routes all emit_event calls to the correct phase tile
    in the frontend — default 2 for Phase 2 agents, pass 1/3/4/5 when
    calling from other phase handlers.
    """
    # Detect the specific challenge for banner copy AND to confirm there
    # IS one to solve before bothering CUA.
    _, reason = await detect_human_verification(page, platform, label)
    platform_key = platform.lower()

    # ── Tier 0: Playwright cheap-click ──
    # Most Cloudflare gates are a single checkbox. A direct Playwright
    # click clears them for zero CUA cost. Keep the banner subtle here —
    # only escalate to "retrying" alert if this attempt fails.
    try:
        clicked = await _playwright_hv_click(page, label)
        if clicked:
            await asyncio.sleep(3)
            blocked, _ = await detect_human_verification(page, platform, label)
            if not blocked:
                log(f"[{label}] Playwright cleared verification ✓ — CUA not needed")
                emit_event("agent_verified", phase=phase, agent=platform_key)
                return True
            log(f"[{label}] Playwright click didn't clear — escalating to CUA", "WARN")
    except Exception as e:
        log(f"[{label}] Playwright HV tier errored: {e} — escalating to CUA", "WARN")

    # ── CUA fallback — first pass (in place, 3 iterations) ──
    # Most Turnstile gates are a single "I am human" checkbox that CUA can
    # click. This keeps us silent in the common case. Only if it can't do we
    # cool down + reload and try once more, or (last) ask the user.
    sys_prompt = (
        "You are looking at a human-verification challenge (Cloudflare, CAPTCHA, or similar) "
        "that is blocking access to an AI agent. If you can see a simple checkbox or button labeled "
        "something like 'I am human', 'Verify', 'Continue', or 'Not a robot' — click it once. "
        "Do NOT try to solve image-selection puzzles or anything requiring complex reasoning. "
        "If there's nothing simple to click, STOP immediately and respond with the word 'blocked'."
    )
    user_prompt = "Click the single human-verification checkbox if one is visible. Otherwise stop and say 'blocked'."
    try:
        log(f"[{label}] Verification detected ({reason or 'unknown'}) — CUA fallback (3 iter, in place)…")
        # Dropdown narration: "trying auto-clear (1/2)…" with a spinning badge.
        emit_event("pipeline_warning", phase=phase, agent=platform_key,
                   message=f"{label} hit a human-verification challenge — trying auto-clear (attempt 1/2)…",
                   details=f"Reason: {reason or 'unknown challenge'}. Running CUA first pass.",
                   alertType="retrying")
        await browser.switch_to_page(page)
        result = await agent_loop(cua_client, browser, sys_prompt, user_prompt,
            model=CUA_MODEL, max_iterations=3, verbose=verbose)
        # Give the page a moment to re-render after a successful click
        await asyncio.sleep(3)
        blocked, _ = await detect_human_verification(page, platform, label)
        if not blocked:
            log(f"[{label}] CUA cleared verification ✓ — proceeding silently")
            # Clear the dropdown badge immediately so the user sees recovery.
            emit_event("agent_verified", phase=phase, agent=platform_key)
            return True
        _cua_text = (result.get("text") or "")[:120]
        log(f"[{label}] CUA first pass didn't clear ({_cua_text}) — cooldown + reload + retry", "WARN")
    except Exception as e:
        log(f"[{label}] CUA first pass errored: {e} — cooldown + reload + retry", "WARN")

    # ── CUA fallback — second pass (cooldown + reload, 5 iterations) ──
    # Cloudflare's bot-score heuristic partially decays with time, and a clean
    # page navigation (blank → original URL) re-runs the stealth init script
    # against a fresh document, which often defuses a recently-flagged session.
    # If Turnstile still fires, CUA gets more iterations this time around
    # since it's our last auto-resort before bothering the user.
    try:
        original_url = page.url
        log(f"[{label}] CUA fallback retry: blank → 3 min cooldown → reload → CUA (5 iter)…")
        # Dropdown narration: "cooling down 3 min…" with a spinning badge. The
        # user knows we haven't given up — we're giving Cloudflare's bot-score
        # decay more room before retrying. 3 min is conservative; shorter
        # windows sometimes still got flagged.
        emit_event("pipeline_warning", phase=phase, agent=platform_key,
                   message=f"{label} auto-clear 1 didn't work — cooling down 3 min, then retrying…",
                   details="Cloudflare bot scores decay with time. Giving the session breathing room.",
                   alertType="retrying")
        try:
            await page.goto("about:blank", wait_until="domcontentloaded", timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(180)
        try:
            await page.goto(original_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(4)
        except Exception as e:
            log(f"[{label}] Reload failed: {e} — escalating to user", "WARN")

        blocked, _ = await detect_human_verification(page, platform, label)
        if blocked:
            log(f"[{label}] Turnstile still present after cooldown — CUA 5-iter retry")
            emit_event("pipeline_warning", phase=phase, agent=platform_key,
                       message=f"{label} still blocked after cooldown — retrying auto-clear (attempt 2/2)…",
                       details="Running CUA second pass with 5 iterations.",
                       alertType="retrying")
            await browser.switch_to_page(page)
            await agent_loop(cua_client, browser, sys_prompt, user_prompt,
                model=CUA_MODEL, max_iterations=5, verbose=verbose)
            await asyncio.sleep(3)
            blocked, _ = await detect_human_verification(page, platform, label)

        if not blocked:
            # Page just reloaded — re-run platform-specific setup so the
            # caller's subsequent paste/send logic still finds Deep Research
            # pill / Opus Adaptive + Research tool / Pro Extended Thinking
            # active on the fresh page.
            log(f"[{label}] CUA retry cleared verification ✓ — re-running setup")
            emit_event("agent_verified", phase=phase, agent=platform_key)
            pl = platform.lower()
            try:
                if pl == "claude":
                    await setup_claude_dr(page)
                elif pl == "gemini":
                    await setup_gemini_dr(page)
                elif pl == "chatgpt":
                    await setup_chatgpt_dr(page)
            except Exception as e:
                log(f"[{label}] Post-clear setup re-run warning: {e}", "WARN")
            return True
        log(f"[{label}] CUA retry still blocked — escalating to tab-kill", "WARN")
    except Exception as e:
        log(f"[{label}] CUA retry errored: {e} — escalating to tab-kill", "WARN")

    # ── Tier 4: Kill the tab, open a fresh one ──
    # NEVER-DIE-MIGRATION-2026-04-18: Last automated tier before
    # surfacing to the user. Close + reopen the page — a fresh cookie
    # context and clean document layout occasionally clears a stubborn
    # bot flag that the cooldown + reload couldn't. Cheap insurance
    # before we interrupt the user.
    try:
        original_url = page.url
        log(f"[{label}] CUA exhausted — killing the tab and re-opening for a clean slate")
        emit_event("pipeline_warning", phase=phase, agent=platform_key,
                   message=f"{label} still blocked — closing & re-opening the tab as a last auto-attempt…",
                   details="Fresh tab with a clean document context — sometimes defuses a stubborn bot flag.",
                   alertType="retrying")
        try:
            await page.close()
        except Exception:
            pass
        page = await browser.new_tab(original_url)
        await asyncio.sleep(4)
        blocked, _ = await detect_human_verification(page, platform, label)
        if not blocked:
            log(f"[{label}] Fresh tab cleared verification ✓ — re-running setup")
            emit_event("agent_verified", phase=phase, agent=platform_key)
            pl = platform.lower()
            try:
                if pl == "claude":
                    await setup_claude_dr(page)
                elif pl == "gemini":
                    await setup_gemini_dr(page)
                elif pl == "chatgpt":
                    await setup_chatgpt_dr(page)
            except Exception as e:
                log(f"[{label}] Post-kill-tab setup re-run warning: {e}", "WARN")
            return True
        log(f"[{label}] Fresh tab still blocked — escalating to user", "WARN")
    except Exception as e:
        log(f"[{label}] Kill-tab tier errored: {e} — escalating to user", "WARN")

    # ── User manual fallback — pause pipeline, banner with Resume/Skip ──
    log(f"[{label}] HUMAN VERIFICATION REQUIRED — {reason or 'unknown challenge'} — pausing pipeline", "WARN")
    emit_event("human_verification_required", phase=phase, agent=platform_key,
               platform=platform_key,
               platformLabel=platform.capitalize(),
               reason=reason or "Human verification challenge",
               message=f"{platform.capitalize()} is asking for human verification. I tried and couldn't clear it — solve it in the browser and tap Resume, or Skip this agent.")
    _controls.request_pause()
    emit_event("pipeline_paused", phase=phase, reason="human_verification_required", agent=platform_key)

    # Poll every 5s — if the user solves the challenge without tapping Resume,
    # we still notice and auto-continue. Also yields to stop/skip/resume signals.
    for _ in range(max_wait_loops):
        await asyncio.sleep(5)
        if _controls.is_stop():
            emit_event("pipeline_stopped", phase=phase, reason="stopped during human_verification", agent=platform_key)
            return False
        # User tapped "Skip agent" in the banner → drop this agent cleanly
        if platform_key in _controls.skipped_agents:
            _controls.skipped_agents.discard(platform_key)
            log(f"[{label}] User chose Skip agent during human verification — dropping {platform_key}", "INFO")
            emit_event("agent_skipped", phase=phase, agent=platform_key,
                       reason="human_verification_skipped")
            emit_event("pipeline_resumed", phase=phase, reason="skip_agent_during_verification", agent=platform_key)
            _controls.request_resume()
            return False
        if not _controls.is_pause():
            # User tapped Resume — verify the challenge is actually cleared
            blocked, _ = await detect_human_verification(page, platform, label)
            if blocked:
                log(f"[{label}] Resume tapped but verification still present — re-pausing", "WARN")
                emit_event("human_verification_required", phase=phase, agent=platform_key,
                           platform=platform_key,
                           platformLabel=platform.capitalize(),
                           reason=reason or "Human verification challenge",
                           message=f"{platform.capitalize()} still shows verification. Solve it first, then Resume.")
                _controls.request_pause()
                continue
            log(f"[{label}] Verification cleared ✓")
            emit_event("pipeline_resumed", phase=phase, reason="human_verification_cleared", agent=platform_key)
            return True
        # Auto-detect clearance even without explicit resume
        blocked, _ = await detect_human_verification(page, platform, label)
        if not blocked:
            log(f"[{label}] Verification auto-cleared ✓")
            _controls.request_resume()
            emit_event("pipeline_resumed", phase=phase, reason="human_verification_cleared", agent=platform_key)
            return True

    log(f"[{label}] Human verification timed out ({max_wait_loops * 5}s) — skipping agent", "WARN")
    return False


async def check_hv_gate(browser, cua_client, platform: str, label: str,
                         phase: int, verbose: bool = False) -> bool:
    """Early HV (human-verification) gate detection + clearance.

    Call this right after `browser.navigate(url)` in any phase handler. If
    the landing page is behind a Cloudflare / CAPTCHA / "verify you are
    human" gate, we resolve it BEFORE spending CUA budget on the phase's
    actual work (selector clicks, prompt submission, etc.) — those would
    fail anyway on a blocked page and burn rate-limit / workspace quota.

    Returns True if the gate is clear (either was never there, or we
    cleared it via CUA / user pause-resume). Returns False if the gate
    couldn't be cleared — caller should abort the phase cleanly.

    Historically only Phase 2 used this; ports to P1/P3/P4/P5 mirror
    `start_agent_no_gemini_wait` but scope events to the caller's phase."""
    try:
        blocked, reason = await detect_human_verification(browser.page, platform, label)
    except Exception as e:
        log(f"[{label}] HV detection errored ({e}) — assuming clear", "WARN")
        return True
    if not blocked:
        return True
    log(f"[{label}] Phase {phase}: HV gate detected ({reason or 'unknown'}) — clearing before phase work", "WARN")
    try:
        return await wait_for_verification_clearance(
            browser, cua_client, browser.page,
            platform=platform, label=label,
            verbose=verbose, phase=phase,
        )
    except Exception as e:
        log(f"[{label}] wait_for_verification_clearance errored: {e}", "WARN")
        return False


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

    # LAYER 0: Detect human-verification gates BEFORE Playwright setup tries to
    # click selectors that don't exist under a Cloudflare / CAPTCHA overlay.
    # If a challenge is present, pause the pipeline and let the user solve it
    # in the browser, then auto-resume when cleared.
    platform_l = platform.lower()
    blocked, reason = await detect_human_verification(page, platform, label)
    if blocked:
        cleared = await wait_for_verification_clearance(browser, cua_client, page, platform, label, verbose=verbose)
        if not cleared:
            emit_event("pipeline_error", phase=2, agent=platform_l,
                       error=f"{platform.capitalize()} human verification unsolved — skipping this agent")
            return page, False
        # Settle after clearance — page often reloads to the real content
        await asyncio.sleep(2)

    # LAYER 1: Playwright-direct setup first
    setup_ok = False
    if platform_l == "chatgpt":
        setup_ok = await setup_chatgpt_dr(page)
    elif platform_l == "gemini":
        setup_ok = await setup_gemini_dr(page)
    elif platform_l == "claude":
        setup_ok = await setup_claude_dr(page)

    # After Playwright tried to set up: if setup failed AND verification is now
    # visible (it can appear mid-setup when Claude's automation detection trips),
    # pause and wait before falling back to CUA.
    if not setup_ok:
        blocked, _ = await detect_human_verification(page, platform, label)
        if blocked:
            cleared = await wait_for_verification_clearance(browser, cua_client, page, platform, label, verbose=verbose)
            if not cleared:
                emit_event("pipeline_error", phase=2, agent=platform_l,
                           error=f"{platform.capitalize()} human verification unsolved — skipping this agent")
                return page, False
            await asyncio.sleep(2)
            # Retry Playwright setup once, now that the challenge is gone
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

    # ── Brief delivery ──
    # Gemini Deep Research ignores file attachments — it only processes text
    # input to generate its research plan. Always paste the brief for Gemini.
    # ChatGPT and Claude: prefer file-attachment (they auto-convert large pastes
    # to attachments and the paste verification then fails).
    is_gemini = platform.lower() == "gemini"
    use_file_attach = brief_path and Path(brief_path).exists() and not is_gemini

    if use_file_attach:
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
                emit_event("pipeline_error", phase=2, agent=platform_l,
                           error="Brief delivery failed (attach + paste)",
                           actions=[
                               {"id": "retry", "label": "Retry",
                                "style": "primary",
                                "command": {"action": "retry_agent", "agent": platform_l}},
                               {"id": "skip", "label": "Skip",
                                "style": "default",
                                "command": {"action": "skip_agent", "agent": platform_l}},
                           ])
                return page, False
    else:
        # Gemini always uses paste; legacy path also uses paste
        if is_gemini:
            log(f"[{label}] Pasting brief directly (Gemini Deep Research requires text input, not file)")
        else:
            log(f"[{label}] Pasting full brief ({len(brief)} chars) with verification...")
        paste_ok = await verified_paste_brief(page, brief, platform, label, max_retries=3)
        if not paste_ok:
            log(f"[{label}] All paste strategies failed — retrying with page reload", "WARN")
            try:
                await page.reload(wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(3)
                # Gemini: re-activate Deep Research after reload
                if is_gemini:
                    await setup_gemini_dr(page)
                    await asyncio.sleep(1)
                paste_ok = await verified_paste_brief(page, brief, platform, label, max_retries=2)
            except Exception as e:
                log(f"[{label}] Reload+retry failed: {e}", "WARN")
        if not paste_ok:
            log(f"[{label}] CRITICAL: Brief paste completely failed — skipping this agent", "ERROR")
            emit_event("pipeline_error", phase=2, agent=platform_l,
                       error="Brief paste failed — could not inject research text",
                       actions=[
                           {"id": "retry", "label": "Retry",
                            "style": "primary",
                            "command": {"action": "retry_agent", "agent": platform_l}},
                           {"id": "skip", "label": "Skip",
                            "style": "default",
                            "command": {"action": "skip_agent", "agent": platform_l}},
                       ])
            return page, False

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
        # CUA send is a last resort — Playwright couldn't find a send button
        # via any selector. The click may or may not have landed depending
        # on what CUA saw. Offer the user [Retry send] [Continue (trust it)]
        # [Skip agent] so they can course-correct without waiting 60s for the
        # agent to (maybe) start generating.
        ag_key_send = (platform or "").lower() or None
        try:
            emit_event("pipeline_warning", phase=2, agent=ag_key_send,
                       message=f"{label}: Send button required CUA fallback — may not have submitted",
                       details=("Playwright couldn't find the Send button via DOM selectors, so CUA "
                                "clicked on what it thought was Send. Retry re-runs the CUA send. "
                                "Skip drops this agent. If you do nothing, the poll continues assuming "
                                "the click landed."),
                       alertType="warn",
                       actions=[
                           {"id": "retry", "label": "Retry",
                            "style": "primary",
                            "command": {"action": "retry_agent", "agent": ag_key_send}},
                           {"id": "skip", "label": "Skip",
                            "style": "default",
                            "command": {"action": "skip_agent", "agent": ag_key_send}},
                       ])
        except Exception:
            pass
        # Wait up to 90s — agent startup is time-sensitive so don't block
        # polling long. Default (timeout) = continue (trust the CUA click).
        if ag_key_send:
            try:
                decision = await _controls.await_agent_decision(ag_key_send, timeout=90.0)
                log(f"[{label}] Send-fallback user decision: {decision}")
                if decision == "retry":
                    try:
                        await browser.switch_to_page(page)
                        await agent_loop(cua_client, browser, PROMPT_CLICK_SEND,
                            "Click the Send button to submit the message. The previous attempt may have missed — look carefully for the Send icon.",
                            model=CUA_MODEL, max_iterations=5, verbose=verbose)
                        log(f"[{label}] CUA send retry attempted")
                    except Exception as e:
                        log(f"[{label}] CUA send retry failed: {e}", "WARN")
                # 'skip' → skipped_agents set already populated; polling loop
                # drops the agent on its next tick. 'continue_partial' /
                # 'timeout' → proceed as-is. 'stop' → outer stop handler.
            except Exception as _e:
                log(f"[{label}] Send-decision wait errored: {_e}", "WARN")

    await asyncio.sleep(3)
    return page, True


async def run_phase2(browser, cua_client, brief_text, verbose=False, enabled_agents=None):
    """Phase 2: ChatGPT → Claude → Gemini (submit+plan) → scrape-pass → Gemini (Start) → Poll all.

    Sequence change: Gemini moved to last of the setup trio. One round-robin scrape
    pass (ChatGPT → Claude → Gemini) is inserted between Gemini's brief submission and
    the 'Start research' click — it primes the frontend with rich agent_progress data
    (sources, partial_text_len, steps) immediately, instead of waiting for the first
    main-rotation poll tick. Gemini stays in 'planning' (never 'complete') until its
    'Start research' button is clicked — gated by scrape_progress_gemini's planning-gate.

    enabled_agents: list of agent keys to run (e.g. ["chatgpt", "gemini"]). None = all."""
    log("=" * 60)
    log("PHASE 2: Deep Research")
    if enabled_agents:
        log(f"  Enabled agents: {enabled_agents}")
    log("  Sequence: ChatGPT → Claude → Gemini (submit+plan) → scrape-pass → Gemini (Start) → Poll all")
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
    chatgpt_page = None
    claude_page = None
    gemini_page = None

    # ── Step 1 (2A): ChatGPT — already in ChatGPT from Phase 1, just open Deep Research ──
    if enabled_agents is None or "chatgpt" in enabled_agents:
        log("\n--- 2A: ChatGPT Deep Research (already in ChatGPT) ---")
        emit_event("agent_progress", phase=2, agent="chatgpt", status="starting", progress="Opening ChatGPT Deep Research mode...")
        for attempt in range(2):
            if attempt > 0:
                log("[2A] Retrying ChatGPT (fresh tab)...", "WARN")
                try: await chatgpt_page.close()
                except Exception: pass
            chatgpt_page, _chatgpt_setup_ok = await start_agent_no_gemini_wait(
                browser, cua_client, "https://chatgpt.com",
                PROMPT_CHATGPT_DEEP_RESEARCH,
                "Enable Deep Research mode in ChatGPT. Do NOT type — just set up and focus input. Say 'ready for paste'.",
                brief_text, "2A", "ChatGPT", verbose, brief_path=brief_path)
            if not _chatgpt_setup_ok:
                # Setup/paste failed — start_agent_no_gemini_wait already
                # emitted pipeline_error with Retry/Skip actions. Don't try
                # to verify — there's nothing to verify.
                verified_a = False
                break
            verified_a = await wait_until_verified(verify_chatgpt_generating, chatgpt_page, "2A",
                browser=browser, cua_client=cua_client, max_retries=15, interval=3, verbose=verbose)
            if verified_a:
                break
        agents["ChatGPT"] = {"page": chatgpt_page, "verified": verified_a, "url": chatgpt_page.url if chatgpt_page else ""}
        if verified_a:
            emit_event("agent_progress", phase=2, agent="chatgpt", status="generating", progress="ChatGPT Deep Research started and verified")
            log("[2A] ChatGPT Deep Research is running ✓")
            await inject_agent_observer(chatgpt_page, "chatgpt")
        else:
            log("[2A] ChatGPT failed after 2 attempts", "ERROR")
            # Mark as terminally failed so the round-robin doesn't sit on it
            # forever waiting for events that will never arrive.
            emit_event("agent_progress", phase=2, agent="chatgpt", status="failed",
                       progress="ChatGPT setup/paste failed — agent did not start.")
            emit_event("pipeline_error", phase=2, agent="chatgpt",
                       error="Failed to start after 2 attempts",
                       actions=[
                           {"id": "retry", "label": "Retry",
                            "style": "primary",
                            "command": {"action": "retry_agent", "agent": "chatgpt"}},
                           {"id": "skip", "label": "Skip",
                            "style": "default",
                            "command": {"action": "skip_agent", "agent": "chatgpt"}},
                       ])
            try:
                _controls.skipped_agents.add("chatgpt")
            except Exception:
                pass
    else:
        log("\n--- 2A: ChatGPT SKIPPED (disabled in config) ---")

    # ── Startup gap: 30s before opening the next agent ──
    # Human-cadence stagger reduces anti-bot signal and lets ChatGPT's DR
    # iframe settle before we start issuing Claude commands. User-locked
    # 2026-04 overhaul: sequential 30s gaps, each agent verify-started
    # before moving on.
    if enabled_agents is None or "claude" in enabled_agents:
        log("\n[Startup gap] Waiting 30s before opening Claude...")
        await asyncio.sleep(30)

    # ── Step 2 (2B): Claude — Opus 4.7 + Adaptive Thinking + Research tool ──
    if enabled_agents is None or "claude" in enabled_agents:
        log("\n--- 2B: Claude Deep Research ---")
        emit_event("agent_progress", phase=2, agent="claude", status="starting", progress="Opening Claude with Opus 4.7 Adaptive + Research tools...")
        for attempt in range(2):
            if attempt > 0:
                log("[2B] Retrying Claude (fresh tab)...", "WARN")
                try: await claude_page.close()
                except Exception: pass
            claude_page, _claude_setup_ok = await start_agent_no_gemini_wait(
                browser, cua_client, "https://claude.ai/new",
                PROMPT_CLAUDE_DEEP_RESEARCH,
                "Select Opus 4.7 + Adaptive Thinking + Research tool. Do NOT type — just set up and focus input. Say 'ready for paste'.",
                brief_text, "2B", "Claude", verbose, brief_path=brief_path)
            if not _claude_setup_ok:
                verified_c = False
                break
            verified_c = await wait_until_verified(verify_claude_generating, claude_page, "2B",
                browser=browser, cua_client=cua_client, max_retries=15, interval=3, verbose=verbose)
            if verified_c:
                break
        agents["Claude"] = {"page": claude_page, "verified": verified_c, "url": claude_page.url if claude_page else ""}
        if verified_c:
            emit_event("agent_progress", phase=2, agent="claude", status="generating", progress="Claude Adaptive Thinking started and verified")
            log("[2B] Claude is running ✓")
            await inject_agent_observer(claude_page, "claude")
        else:
            log("[2B] Claude failed after 2 attempts", "ERROR")
            emit_event("agent_progress", phase=2, agent="claude", status="failed",
                       progress="Claude setup/paste failed — agent did not start.")
            emit_event("pipeline_error", phase=2, agent="claude",
                       error="Failed to start after 2 attempts",
                       actions=[
                           {"id": "retry", "label": "Retry",
                            "style": "primary",
                            "command": {"action": "retry_agent", "agent": "claude"}},
                           {"id": "skip", "label": "Skip",
                            "style": "default",
                            "command": {"action": "skip_agent", "agent": "claude"}},
                       ])
            try:
                _controls.skipped_agents.add("claude")
            except Exception:
                pass
    else:
        log("\n--- 2B: Claude SKIPPED (disabled in config) ---")

    # ── Startup gap: 30s before opening Gemini ──
    if enabled_agents is None or "gemini" in enabled_agents:
        log("\n[Startup gap] Waiting 30s before opening Gemini...")
        await asyncio.sleep(30)

    # ── Step 3 (2C): Gemini — submit brief, let it generate plan (don't click Start yet) ──
    gemini_setup_ok = False
    if enabled_agents is None or "gemini" in enabled_agents:
        log("\n--- 2C: Gemini Deep Research (submit + let it plan) ---")
        emit_event("agent_progress", phase=2, agent="gemini", status="starting", progress="Opening Gemini and submitting research brief...")
        gemini_page, gemini_setup_ok = await start_agent_no_gemini_wait(
            browser, cua_client, "https://gemini.google.com",
            PROMPT_GEMINI_DEEP_RESEARCH,
            "Enable Deep Research mode in Gemini. Do NOT type — just set up and focus input. Say 'ready for paste'.",
            brief_text, "2C", "Gemini", verbose, brief_path=brief_path)
        if gemini_setup_ok:
            log("[2C] Gemini brief submitted — letting it generate research plan")
            emit_event("agent_progress", phase=2, agent="gemini", status="generating", progress="Gemini generating research plan...")
        else:
            # Setup or paste failed — start_agent_no_gemini_wait already emitted
            # pipeline_error with Retry/Skip actions. Mark Gemini terminally
            # failed so the [2D] wait loop is skipped and the round-robin
            # poller treats it as done. No more lying about "generating plan".
            log("[2C] Gemini setup/paste failed — marking agent failed, skipping [2D] plan wait", "ERROR")
            emit_event("agent_progress", phase=2, agent="gemini", status="failed",
                       progress="Gemini setup/paste failed — agent did not start.")
            try:
                _controls.skipped_agents.add("gemini")
            except Exception:
                pass
    else:
        log("\n--- 2C: Gemini SKIPPED (disabled in config) ---")

    # ── First wave: 60s sequential per agent (2026-04 overhaul) ──
    # Instead of one instant snapshot, dwell on each agent's tab for 60s and
    # emit agent_progress every ~15s. This gives the frontend a richer,
    # ladder-like narration start while staying at human cadence. Sequence
    # order matches the original submission: ChatGPT → Claude → Gemini.
    # Gemini's planning-gate inside scrape_progress_gemini keeps its status
    # pinned to 'planning' while the Start-research button is still visible.
    # 2026-04-25: First-wave dwell DROPPED from 60s/agent (180s total) to 0s.
    # Round-robin starts immediately and emits agent_progress live as it
    # observes each tab; the dwell delayed real round-robin start without
    # adding signal the round-robin couldn't deliver itself.
    log("\n--- 2 first-wave (skipped — round-robin starts immediately) ---")
    _scrape_targets = [
        ("chatgpt", "ChatGPT", chatgpt_page, scrape_progress_chatgpt),
        ("claude",  "Claude",  claude_page,  scrape_progress_claude),
        ("gemini",  "Gemini",  gemini_page,  scrape_progress_gemini),
    ]
    _FIRST_WAVE_SEC = 0
    _FIRST_WAVE_TICK = 15
    for _ag_key, _ag_name, _ag_page, _scrape_fn in _scrape_targets:
        if _ag_page is None:
            continue
        try:
            await browser.switch_to_page(_ag_page)
            await asyncio.sleep(1)
        except Exception as _e:
            log(f"  [First-wave] switch to {_ag_name} failed: {_e}", "WARN")
            continue
        log(f"  [First-wave] Dwelling on {_ag_name} for {_FIRST_WAVE_SEC}s...")
        _wave_start = time.time()
        _last_emit_len = -1
        while time.time() - _wave_start < _FIRST_WAVE_SEC:
            try:
                _snap = await _scrape_fn(_ag_page) or {}
                if _ag_key == "gemini":
                    _st = (_snap.get("status") or "").lower()
                    if _st in ("complete", "done"):
                        _snap["status"] = "generating"
                        _snap["phase"] = "planning"
                _sources = int(_snap.get("sources", 0) or 0)
                _partial = int(_snap.get("partial_text_len", 0) or 0)
                _steps = _snap.get("steps", []) or []
                _progress = _snap.get("progress") or (
                    f"Working — {_sources} sources, {_partial} chars" if _partial else
                    (_steps[-1] if _steps else f"{_ag_name} starting up")
                )
                # Only emit if something actually changed to avoid frontend churn
                if _partial != _last_emit_len or _last_emit_len < 0:
                    emit_event("agent_progress", phase=2, agent=_ag_key,
                               status=_snap.get("status", "generating"),
                               progress=_progress,
                               sources=_sources,
                               source_urls=(_snap.get("source_urls", []) or [])[:10],
                               partial_text_len=_partial,
                               steps=_steps[-3:] if _steps else [],
                               thinking=(_snap.get("thinking") or "")[:300])
                    _last_emit_len = _partial
                    log(f"  [First-wave/{_ag_name}] status={_snap.get('status')}, "
                        f"sources={_sources}, partial_len={_partial}")
            except Exception as _e:
                log(f"  [First-wave/{_ag_name}] tick failed (non-fatal): {_e}", "WARN")
            await asyncio.sleep(_FIRST_WAVE_TICK)

    # ── Step 4 (2D): Return to Gemini — wait for plan + click "Start research" ──
    # 2026-04 overhaul: no rotation to ChatGPT/Claude during this wait. We
    # dwell on the Gemini tab until the Start-research button is clicked;
    # the OFFICIAL round-robin only begins after that click. ChatGPT/Claude
    # keep running in the background — their state from the first-wave dwell
    # is the last frontend update until the round-robin picks them up.
    #
    # Skip the entire [2D] loop if Gemini's setup failed (setup_ok == False)
    # OR was marked skipped (e.g. via Retry/Skip Skip path). Without this
    # gate the loop sits 10 minutes waiting for a "Start research" button
    # that will never appear because no plan was ever generated.
    _gemini_skipped = False
    try:
        _gemini_skipped = "gemini" in (_controls.skipped_agents or set())
    except Exception:
        _gemini_skipped = False
    if gemini_page is not None and gemini_setup_ok and not _gemini_skipped:
        log("\n--- 2D: Gemini — waiting for research plan + clicking 'Start research' (focused, no rotation) ---")
        await browser.switch_to_page(gemini_page)
        await asyncio.sleep(2)

        start_clicked = False
        _start_wait_max_sec = 10 * 60
        _loop_start = time.time()
        _last_plan_emit = 0.0
        while time.time() - _loop_start < _start_wait_max_sec:
            # 1. Check Start-research button on Gemini and click if present
            try:
                await browser.switch_to_page(gemini_page)
                clicked = await gemini_page.evaluate("""() => {
                    const btns = document.querySelectorAll('button');
                    for (const b of btns) {
                        const txt = b.textContent.trim().toLowerCase();
                        if (txt.includes('start research')) { b.click(); return true; }
                    }
                    return false;
                }""")
                if clicked:
                    log("[2D] Clicked 'Start research' via JS ✓")
                    start_clicked = True
                    await asyncio.sleep(5)
                    break
            except Exception:
                pass

            # 2. Emit a Gemini planning heartbeat every ~60s so the frontend
            # knows Gemini is still drafting the plan. No rotation — we do
            # NOT scrape ChatGPT/Claude here; they kept their first-wave
            # state and will refresh on the official round-robin.
            if time.time() - _last_plan_emit >= 60:
                try:
                    _gm = await scrape_progress_gemini(gemini_page) or {}
                    _gm_status = (_gm.get("status") or "generating")
                    if _gm_status in ("complete", "done"):
                        _gm_status = "generating"
                    emit_event("agent_progress", phase=2, agent="gemini",
                               status=_gm_status,
                               progress=_gm.get("progress") or "Gemini drafting research plan...",
                               sources=int(_gm.get("sources", 0) or 0),
                               source_urls=(_gm.get("source_urls", []) or [])[:10],
                               partial_text_len=int(_gm.get("partial_text_len", 0) or 0),
                               steps=(_gm.get("steps") or [])[-3:],
                               plan=(_gm.get("plan") or "")[:500])
                    _last_plan_emit = time.time()
                except Exception:
                    pass

            _elapsed = int(time.time() - _loop_start)
            log(f"[2D] Still waiting for Gemini research plan... ({_elapsed}s / {_start_wait_max_sec}s)")
            await asyncio.sleep(30)

        # CUA fallback for Start research
        if not start_clicked:
            log("[2D] JS couldn't find button — CUA clicking 'Start research'")
            await browser.switch_to_page(gemini_page)
            fix = await agent_loop(cua_client, browser,
                PROMPT_GEMINI_START_RESEARCH,
                "Click the 'Start research' button to begin the deep research.",
                model=CUA_MODEL, max_iterations=10, verbose=verbose)
            fix_text = (fix.get("text") or "").lower()
            if "click" in fix_text:
                start_clicked = True
                log("[2D] CUA clicked 'Start research' ✓")
                await asyncio.sleep(5)

        # Verify Gemini is actually researching
        verified_b = await wait_until_verified(verify_gemini_generating, gemini_page, "2D",
            browser=browser, cua_client=cua_client, max_retries=15, interval=3, verbose=verbose)
        # Record when research actually started (after "Start research" click)
        # so the round-robin doesn't check for completion prematurely
        agents["Gemini"] = {"page": gemini_page, "verified": verified_b, "url": gemini_page.url,
                            "research_started_at": time.time()}
        if verified_b:
            emit_event("agent_progress", phase=2, agent="gemini", status="generating", progress="Gemini Deep Research plan created and started")
            log("[2D] Gemini is researching ✓")
            await inject_agent_observer(gemini_page, "gemini")
        else:
            log("[2D] Gemini may not be running", "WARN")

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

async def run_phase3_upload(browser, cua_client, results, topic, queue_dir, verbose=False):
    """Phase 3 (step a): Get shareable links + upload MDs to NotebookLM + make public."""
    log("=" * 60)
    log("PHASE 3: Extract Links + NotebookLM Upload")
    log("=" * 60)

    # 2026-04-26: log every MD on disk in queue_dir/documents/ at P3 entry.
    # Makes P2→P3 handoff debugging trivial — we can see at a glance which
    # of the 3 agent .md files made it to disk and at what size. If one is
    # missing or 0 bytes, P3 NotebookLM upload will silently miss that
    # source.
    try:
        _docs = queue_dir / "documents"
        if _docs.exists():
            _on_disk = [(f.name, f.stat().st_size) for f in sorted(_docs.glob("*.md"))]
            log(f"Phase 3: queue MDs on disk: " +
                (", ".join(f"{n}={s}b" for n, s in _on_disk) if _on_disk else "(none)"))
        else:
            log("Phase 3: queue_dir/documents does not exist — no MDs", "WARN")
    except Exception as _de:
        log(f"Phase 3: MD-on-disk audit failed: {_de}", "DEBUG")

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
        agent_key = name.lower().replace(" ", "")
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
            # Emit link immediately — don't wait for phase end
            emit_validated_link(3, agent_key, links[name], f"{name} Research")
        except Exception as e:
            links[name] = r.get("url", "")
            log(f"[{name}] Link error: {e} — using chat URL", "WARN")
            if links[name]:
                emit_event("link_extracted", phase=3, agent=agent_key,
                           url=links[name], label=f"{name} Research", verified=False)
            # Surface the extraction failure so the per-agent dropdown in
            # Phase 3 shows WHY the share link is unverified. Warn (not
            # error) because we still have the chat URL as a fallback and
            # Phase 3 proceeds with NotebookLM upload regardless.
            try:
                emit_event("pipeline_warning", phase=3, agent=agent_key,
                           message=f"{name}: couldn't extract verified share link — using chat URL as fallback",
                           details=f"CUA couldn't get a public share link for this agent. Falling back to the raw chat URL (may require login to view). Error: {str(e)[:150]}",
                           alertType="warn")
            except Exception:
                pass

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

    # Upload MDs to NotebookLM (wrapped in retry loop — user can re-attempt
    # after a login-expired or generic upload failure without losing the rest
    # of the pipeline).
    notebook_url = ""
    p3_max_retries = 2
    p3_attempt = 0
    while md_files and p3_attempt <= p3_max_retries:
        log(f"\n--- Uploading {len(md_files)} MDs to NotebookLM (attempt {p3_attempt + 1}/{p3_max_retries + 1}) ---")
        try:
            page = await browser.new_tab("https://notebooklm.google.com")
            await asyncio.sleep(4)

            # Early HV check — NotebookLM occasionally hits Google's bot gate
            # on fresh tabs when the session fingerprint looks suspicious.
            # Clearing first avoids wasted CUA calls on a blocked page.
            if cua_client:
                cleared = await check_hv_gate(browser, cua_client, "notebooklm", "NotebookLM",
                                               phase=3, verbose=verbose)
                if not cleared:
                    log("Phase 3: HV gate on NotebookLM could not be cleared — retrying or aborting", "ERROR")
                    p3_attempt += 1
                    continue

            for i, md_path in enumerate(md_files):
                log(f"Uploading {md_path.name} ({i+1}/{len(md_files)})...")
                emit_event("agent_progress", phase=3, agent="notebooklm",
                           status="uploading",
                           progress=f"Uploading source {i+1}/{len(md_files)}: {md_path.name}")
                browser.set_upload_file(str(md_path))

                _stop, _task = start_narration_ticker(
                    3, "notebooklm",
                    f"NotebookLM uploading source {i+1}/{len(md_files)}: {md_path.name}",
                    interval=20)
                try:
                    if i == 0:
                        await agent_loop(cua_client, browser, PROMPT_NOTEBOOKLM_UPLOAD,
                            "Create a new notebook and upload the first file. File dialog is auto-handled.",
                            model=CUA_MODEL, max_iterations=15, verbose=verbose)
                    else:
                        await agent_loop(cua_client, browser, PROMPT_NOTEBOOKLM_UPLOAD,
                            f"Add another source (file {i+1}). Click 'Add source' or '+'. File dialog is auto-handled.",
                            model=CUA_MODEL, max_iterations=10, verbose=verbose)
                finally:
                    await stop_narration_ticker(_stop, _task)

                browser.clear_upload_file()
                await asyncio.sleep(3)

            # Rename notebook — use the smart title (Firestore-synced) so NotebookLM,
            # YouTube, and the email subject all line up on the same short name.
            title = smart_title(topic)
            log(f"Renaming notebook to '{title}'...")
            emit_event("agent_progress", phase=3, agent="notebooklm",
                       status="renaming",
                       progress=f"Renaming notebook to '{title}'…")
            await agent_loop(cua_client, browser, PROMPT_NOTEBOOKLM_RENAME,
                f"Rename this notebook to: {title}",
                model=CUA_MODEL, max_iterations=8, verbose=verbose)

            # C1: make notebook public (Share → "Anyone with the link" → Save)
            # BEFORE emitting the URL, so the frontend's link is always viewable.
            emit_event("agent_progress", phase=3, agent="notebooklm",
                       status="sharing",
                       progress="Setting notebook to 'Anyone with the link can view'…")
            notebook_url = await browser.current_url()
            try:
                log("NotebookLM: opening share dialog to set 'Anyone with link'...")
                nlm_share_res = await extract_notebooklm_url(browser, cua_client=cua_client, verbose=verbose)
                if nlm_share_res.verified and nlm_share_res.url:
                    notebook_url = nlm_share_res.url
                    log(f"NotebookLM public share OK: {notebook_url}")
                else:
                    log(f"NotebookLM public share uncertain — falling back to tab URL: {nlm_share_res.error}", "WARN")
            except Exception as e:
                log(f"NotebookLM public share flow error: {e} — falling back to tab URL", "WARN")
            log(f"NotebookLM: {notebook_url}")
            # Emit notebook link immediately — frontend shows it without waiting for phase end
            if notebook_url and "notebooklm.google.com/notebook" in notebook_url:
                emit_validated_link(3, "notebooklm", notebook_url, "NotebookLM Notebook")
            save_track("NotebookLM", {"status": "uploaded", "notebook_url": notebook_url,
                                       "sources_count": len(md_files)})
            break  # Successful upload — exit retry loop
        except Exception as e:
            log(f"NotebookLM upload error: {e}", "ERROR")
            # Distinguish session-expired from generic upload failure — the
            # frontend can offer "re-login then retry" vs "just retry".
            _err_msg = str(e)
            _low = _err_msg.lower()
            is_login_err = any(k in _low for k in ("login", "signin", "auth", "unauthor"))
            retries_left = max(0, p3_max_retries - p3_attempt)
            p3_actions = []
            if retries_left > 0:
                if is_login_err:
                    p3_actions.append({
                        "id": "retry",
                        "label": f"I've logged in — Retry ({retries_left} left)",
                        "style": "primary",
                        "command": {"action": "retry_phase", "phase": 3},
                    })
                else:
                    p3_actions.append({
                        "id": "retry",
                        "label": f"Retry upload ({retries_left} left)",
                        "style": "primary",
                        "command": {"action": "retry_phase", "phase": 3},
                    })
            p3_actions.append({
                "id": "skip", "label": "Skip NotebookLM",
                "style": "default" if retries_left > 0 else "primary",
                "command": {"action": "skip_phase", "phase": 3},
            })
            if is_login_err:
                emit_event("pipeline_error", phase=3, agent="notebooklm",
                           error=f"NotebookLM login appears expired — re-authenticate in the browser and hit Retry. Details: {_err_msg[:200]}",
                           actions=p3_actions)
            else:
                emit_event("pipeline_error", phase=3, agent="notebooklm",
                           error=f"NotebookLM upload failed: {_err_msg[:300]}",
                           actions=p3_actions)
            # Wait up to 10 min for user decision. Retry → re-run upload; skip →
            # proceed without NotebookLM; timeout → skip (don't hang pipeline).
            if retries_left > 0:
                p3_decision = await _controls.await_retry_or_continue(phase=3, timeout=600.0)
                log(f"Phase 3 upload decision: {p3_decision}")
                if p3_decision == "stop":
                    break
                if p3_decision == "retry":
                    p3_attempt += 1
                    # Close the (possibly borked) NotebookLM tab so the retry
                    # opens a clean one.
                    try:
                        await page.close()
                    except Exception:
                        pass
                    try:
                        emit_event("phase_restart", phase=3,
                                   reason="user_retry_notebooklm_upload",
                                   attempt=p3_attempt + 1)
                    except Exception:
                        pass
                    continue  # retry the upload loop
                # continue_anyway / skip / timeout → break out; proceed with empty notebook_url
                break
            else:
                # No retries left — log and proceed with empty notebook_url
                log("Phase 3: No NotebookLM retries left — proceeding without it", "WARN")
                break
    if not md_files:
        log("No MD files to upload to NotebookLM", "WARN")
        emit_event("pipeline_warning", phase=3, agent="notebooklm",
                   message="No research documents to upload to NotebookLM",
                   details="Phase 2 produced no .md files. NotebookLM needs at least one source. Check Phase 2 dropdowns for agent failures.",
                   alertType="warn")

    return {"links": links, "notebook_url": notebook_url, "md_files": [str(p) for p in md_files]}


# ── Phase 4: Audio Overview Generation ───────────────────────────────────────

async def run_phase3_audio(browser, cua_client, notebook_url, queue_dir, verbose=False):
    """Phase 3 (step b): Generate long-form audio overview in NotebookLM + share public."""
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

    # Early HV gate check — NotebookLM occasionally sits behind Google's bot
    # challenge when the session fingerprint drifts. Clearing it upfront
    # saves us from a cascade of failed CUA clicks that would consume
    # workspace quota without moving forward.
    if cua_client:
        cleared = await check_hv_gate(browser, cua_client, "notebooklm", "NotebookLM",
                                       phase=4, verbose=verbose)
        if not cleared:
            log("Phase 4: HV gate on NotebookLM could not be cleared — aborting audio step", "ERROR")
            return {"audio_path": None}

    # Wrap generation + polling in a retry loop so the user can re-trigger
    # audio generation from scratch if the first attempt times out.
    audio_done = False
    p4_max_retries = 1
    p4_attempt = 0

    while p4_attempt <= p4_max_retries and not audio_done and not _controls.is_stop():
        if p4_attempt > 0:
            log(f"Phase 4: Retrying audio generation (attempt {p4_attempt + 1}/{p4_max_retries + 1})")
            try:
                emit_event("phase_restart", phase=4,
                           reason="user_retry_audio",
                           attempt=p4_attempt + 1)
            except Exception:
                pass
            # Reload notebook for a clean retry
            try:
                await browser.navigate(notebook_url)
                await asyncio.sleep(4)
            except Exception:
                pass

        # Check if audio is ALREADY generating (prevent double click)
        already_generating = await _check_audio_generating(browser.page)
        if already_generating:
            log("Audio already generating — skipping Generate click")
        else:
            log("Starting audio generation (Long + Deep dive)...")
            _stop, _task = start_narration_ticker(
                4, "notebooklm",
                "Configuring audio overview (Long + Deep dive) and clicking Generate",
                interval=20)
            try:
                await agent_loop(cua_client, browser, PROMPT_AUDIO_GENERATE,
                    "Generate ONE audio overview. Select all sources, set Long + Deep dive, click Generate ONCE. Say 'generating' when started.",
                    model=CUA_MODEL, max_iterations=15, verbose=verbose)
            finally:
                await stop_narration_ticker(_stop, _task)

        # Verify it started
        verified = await wait_until_verified(
            lambda page: _check_audio_generating(page),
            browser.page, "Phase4", browser=browser, cua_client=cua_client,
            max_retries=10, interval=5, verbose=verbose)

        if not verified:
            log("Could not verify audio generation started", "WARN")

        # Minimum 2 minute wait — audio generation typically starts within 1-2 min;
        # waiting 5 min was burning slack for no reason. First poll at 2 min is
        # safe (NotebookLM has reliably emitted progress signals by then).
        log("Waiting 2 minutes before first audio check (generation takes ~10-20 min)...")
        interrupt = await _controls.interruptible_sleep(2 * 60, check_interval=10)
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
            # Live narration tick — without this the FE dropdown sits on the
            # last pre-poll string ("Setting notebook to…") for the full 45-min
            # audio window. Match the P2 round-robin cadence.
            try:
                emit_event("agent_progress", phase=4, agent="notebooklm",
                           status="generating",
                           progress=f"NotebookLM still generating audio overview… "
                                    f"({elapsed_min}m total / ~15m typical)",
                           elapsedSec=elapsed_min * 60,
                           expectedMinutes=15)
            except Exception:
                pass
            interrupt = await _controls.interruptible_sleep(90, check_interval=10)
            if interrupt == "stop":
                log("[Phase4] STOP during poll wait — aborting")
                break
            if interrupt == "pause":
                emit_event("pipeline_paused", phase=4)
                await _controls.wait_if_paused()
                if _controls.is_stop():
                    break

        # End of inner poll loop. If we broke out due to completion, exit
        # the retry loop too. Otherwise (timeout without done), offer retry.
        if audio_done or _controls.is_stop():
            break

        # Timeout: offer user [Retry audio] / [Skip audio]. Skip routes
        # through the standard skip_phase command; retry restarts generation
        # from scratch.
        retries_left = max(0, p4_max_retries - p4_attempt)
        p4_actions = []
        if retries_left > 0:
            p4_actions.append({
                "id": "retry", "label": f"Retry audio ({retries_left} left)",
                "style": "primary",
                "command": {"action": "retry_phase", "phase": 4},
            })
        p4_actions.append({
            "id": "skip_phase", "label": "Skip audio",
            "style": "default" if retries_left > 0 else "primary",
            "command": {"action": "skip_phase", "phase": 4},
        })
        try:
            emit_event("pipeline_warning", phase=4, agent="notebooklm",
                       message=f"NotebookLM audio generation timed out (45 min cap, attempt {p4_attempt + 1}/{p4_max_retries + 1})",
                       details=("The audio overview didn't finish within the polling budget. "
                                "Retry regenerates from scratch. Skip proceeds to Phase 5/6 with "
                                "the written report + links (no audio, no YouTube)."),
                       alertType="warn",
                       actions=p4_actions)
        except Exception:
            pass
        if retries_left > 0:
            # Wait up to 10 min for user choice. Default = skip (don't hang).
            p4_decision = await _controls.await_retry_or_continue(phase=4, timeout=600.0)
            log(f"Phase 4 timeout decision: {p4_decision}")
            if p4_decision == "retry":
                p4_attempt += 1
                continue
            if p4_decision == "stop":
                break
            # continue_anyway / skip / timeout → exit retry loop
            break
        else:
            log("Phase 4: No audio retries left — proceeding without audio", "WARN")
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

        emit_event("agent_progress", phase=4, agent="notebooklm",
                   status="downloading",
                   progress="Downloading audio file from NotebookLM…")
        _stop_d, _task_d = start_narration_ticker(
            4, "notebooklm",
            "Downloading audio overview .m4a from NotebookLM",
            interval=20)
        try:
            await agent_loop(cua_client, browser, PROMPT_AUDIO_DOWNLOAD,
                "Download the audio file.", model=CUA_MODEL, max_iterations=8, verbose=verbose)
        finally:
            await stop_narration_ticker(_stop_d, _task_d)

        # Wait up to 30s for download event
        try:
            audio_path = await asyncio.wait_for(download_future, timeout=30)
        except asyncio.TimeoutError:
            log("Download event not received — checking common download dirs...", "WARN")
            # Warn (not error) — we have a fallback that scans Downloads/.
            # Only error-emit if the fallback also fails (see below).
            try:
                emit_event("pipeline_warning", phase=4, agent="notebooklm",
                           message="Audio download timed out — scanning Downloads folder for fallback",
                           details="Playwright's download event didn't fire within 30s. NotebookLM may have downloaded the file via its own handler; we'll check common Downloads locations next.",
                           alertType="retrying")
            except Exception:
                pass
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

        # If we got here with audio_done=True but no audio_path, both the
        # Playwright download event AND the Downloads-folder scan failed.
        # That's a real error — surface it so the user knows Phase 5 will
        # skip and can decide whether to re-run or accept report-only.
        if not audio_path:
            try:
                emit_event("pipeline_error", phase=4, agent="notebooklm",
                           error="Audio file downloaded by NotebookLM but we couldn't locate it on disk (Playwright event didn't fire and Downloads folder scan found nothing). Phase 5 will be skipped.",
                           actions=[
                               {"id": "skip_phase", "label": "Skip audio — proceed to report",
                                "style": "primary",
                                "command": {"action": "skip_phase", "phase": 4}},
                           ])
            except Exception:
                pass

    # ── Extract NotebookLM Audio Overview shareable link ──
    # Audio overview share: three-dots/menu → Share → Notebook access → public → get link → Save
    audio_overview_url = ""
    if audio_done:
        try:
            page = browser.page
            # Step 1: Open three-dots / options menu near the audio player
            menu_opened = await page.evaluate("""() => {
                // Look for three-dots / more options button near audio player
                const menuBtns = document.querySelectorAll(
                    'button[aria-label*="More"], button[aria-label*="more"], ' +
                    'button[aria-label*="Options"], button[aria-label*="options"], ' +
                    'button[aria-label*="Menu"], button[aria-label*="menu"], ' +
                    '[class*="more"] button, [class*="menu"] button, ' +
                    'button[data-testid*="more"], button[data-testid*="menu"]'
                );
                // Also look for ⋮ (vertical dots) button
                for (const btn of menuBtns) {
                    if (btn.offsetParent !== null) { btn.click(); return 'menu_opened'; }
                }
                // Fallback: look for button with dots icon/text
                const allBtns = document.querySelectorAll('button');
                for (const b of allBtns) {
                    const txt = (b.innerText || '').trim();
                    const label = (b.getAttribute('aria-label') || '').toLowerCase();
                    if (txt === '⋮' || txt === '...' || txt === '⋯' ||
                        label.includes('action') || label.includes('overflow')) {
                        if (b.offsetParent !== null) { b.click(); return 'dots_opened'; }
                    }
                }
                return '';
            }""")
            if menu_opened:
                await asyncio.sleep(1)
                # Step 2: Click "Share" from the menu
                await page.evaluate("""() => {
                    const items = document.querySelectorAll(
                        '[role="menuitem"], [role="option"], li, button'
                    );
                    for (const item of items) {
                        const txt = (item.innerText || item.textContent || '').toLowerCase().trim();
                        if (txt === 'share' || txt === 'share notebook' || txt.startsWith('share')) {
                            item.click();
                            return 'share_clicked';
                        }
                    }
                    return '';
                }""")
                await asyncio.sleep(2)
            else:
                # Fallback: try direct share button
                await page.evaluate("""() => {
                    const shareBtn = document.querySelector(
                        'button[aria-label*="Share"], button[aria-label*="share"]'
                    );
                    if (shareBtn) shareBtn.click();
                    return '';
                }""")
                await asyncio.sleep(2)

            # Step 3: Use shared helper for NLM public access + get link + Save.
            # Helper returns (url, public_verified). Audio share doesn't have
            # a separate downstream consumer that gates on public_verified —
            # we still log it for diagnostic purposes and proceed.
            audio_overview_url, audio_public_verified = await _set_nlm_public_and_get_link(page, "Audio")
            if audio_public_verified:
                log("[Audio] Public share DOM-verified")
            else:
                log("[Audio] Public share NOT DOM-verified — audio link may be private", "WARN")

            if not audio_overview_url:
                # Fallback: use current URL
                current_url = await browser.current_url()
                if "notebooklm.google.com/notebook" in current_url:
                    audio_overview_url = current_url

            await page.keyboard.press("Escape")  # Close any remaining dialog
            await asyncio.sleep(0.5)
        except Exception as e:
            log(f"Audio overview link extraction failed: {e}", "WARN")
        if audio_overview_url:
            log(f"Audio overview link: {audio_overview_url}")
            # Emit link immediately — route through validate_link to prevent fake URLs
            emit_validated_link(3, "notebooklm", audio_overview_url, "Audio Overview")
        else:
            log("Audio overview link not found — using notebook URL as fallback", "WARN")

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
            # Storage upload is best-effort — local playback still works via
            # the backend, and Phase 5 can still upload to YouTube from the
            # local file. Warn (not error) if it failed.
            if not audio_url:
                try:
                    emit_event("pipeline_warning", phase=4, agent="notebooklm",
                               message="Firebase Storage upload failed — audio still saved locally",
                               details="The audio file couldn't be synced to Firebase Storage (used by the Podcasts page on the web app). Local pipeline is unaffected — Phase 5 can still upload to YouTube from the local file.",
                               alertType="warn")
                except Exception:
                    pass
        except Exception as e:
            log(f"Audio Firestore/Storage sync failed: {e}", "WARN")
            try:
                emit_event("pipeline_warning", phase=4, agent="notebooklm",
                           message="Firebase sync failed — audio still saved locally",
                           details=f"{str(e)[:200]}",
                           alertType="warn")
            except Exception:
                pass

    return {"audio_path": audio_path, "audio_overview_url": audio_overview_url}


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

GEMINI_API_KEY = get_env("GEMINI_API_KEY")  # For thumbnail generation (nano-banana)
THUMBNAIL_MODEL = os.environ.get("THUMBNAIL_MODEL", "gemini-2.5-flash-image")  # nano-banana


def generate_thumbnail(topic, output_path):
    """Generate a topic-relevant thumbnail via Gemini 2.5 Flash Image (nano-banana).
    Falls back to Pillow text card if the API call fails."""
    try:
        import requests
        prompt = (
            f"Create a professional, modern YouTube thumbnail for a research video about: "
            f"{topic[:200]}. Dark futuristic theme, clean design, abstract tech visuals. "
            f"No text on the image — just visual design. 16:9 aspect ratio."
        )
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{THUMBNAIL_MODEL}:generateContent?key={GEMINI_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }
        resp = requests.post(url, json=payload, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            for candidate in data.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if "inlineData" in part:
                        img_data = base64.b64decode(part["inlineData"]["data"])
                        Path(output_path).write_bytes(img_data)
                        log(f"Thumbnail generated via {THUMBNAIL_MODEL} ✓ ({len(img_data)} bytes)")
                        return
        log(f"{THUMBNAIL_MODEL} returned {resp.status_code} — falling back to Pillow", "WARN")
    except Exception as e:
        log(f"{THUMBNAIL_MODEL} image gen failed: {e} — falling back to Pillow", "WARN")

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


async def run_phase4(browser, cua_client, audio_path, topic, queue_dir,
                     links=None, notebook_url="", verbose=False):
    """Phase 4: Convert audio to video + upload to YouTube (unlisted, not-for-kids)."""
    log("=" * 60)
    log("PHASE 5: Video + YouTube Upload")
    log("=" * 60)

    if not audio_path or not Path(audio_path).exists():
        log("No audio file — skipping Phase 5", "WARN")
        return {"youtube_url": ""}

    video_dir = queue_dir / "video"
    video_dir.mkdir(exist_ok=True)

    # Generate thumbnail (Gemini Imagen → Pillow fallback) — save to queues root
    emit_event("agent_progress", phase=4, agent="youtube",
               status="rendering_thumbnail",
               progress="Generating video thumbnail (Gemini Imagen)…")
    title_card = queue_dir / "thumbnail.png"
    generate_thumbnail(topic, title_card)

    # ffmpeg: audio + title card → MP4
    video_path = video_dir / "research_overview.mp4"
    emit_event("agent_progress", phase=4, agent="youtube",
               status="wrapping_video",
               progress="Wrapping audio + thumbnail into MP4 (ffmpeg)…")
    log("Converting audio to video (ffmpeg)...")
    try:
        cmd = ["ffmpeg", "-y", "-loop", "1", "-framerate", "2", "-i", str(title_card),
               "-i", str(audio_path), "-c:v", "libx264", "-tune", "stillimage",
               "-c:a", "aac", "-b:a", "192k", "-r", "2", "-pix_fmt", "yuv420p",
               "-shortest", str(video_path)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            log(f"ffmpeg error: {r.stderr[:300]}", "ERROR")
            # Disk-full is a common cause — call it out if the stderr
            # mentions it so the user knows to clear space.
            _err_tail = (r.stderr or "")[-300:]
            if "no space" in _err_tail.lower() or "disk full" in _err_tail.lower() or "enospc" in _err_tail.lower():
                emit_event("pipeline_error", phase=4, agent="youtube",
                           error=f"Disk full while writing video — free up space and resume. Details: {_err_tail[:200]}")
            else:
                emit_event("pipeline_error", phase=4, agent="youtube",
                           error=f"ffmpeg failed to build the video from audio+thumbnail. Phase 5 cannot proceed. Details: {_err_tail[:200]}")
            return {"youtube_url": ""}
        log(f"Video: {video_path} ({video_path.stat().st_size / 1024 / 1024:.1f}MB)")
        save_track("Phase5", {"status": "video_created", "size_mb": round(video_path.stat().st_size / 1024 / 1024, 1)})
    except Exception as e:
        log(f"ffmpeg failed: {e}", "ERROR")
        _err_msg = str(e)
        _low = _err_msg.lower()
        if "no space" in _low or "enospc" in _low:
            emit_event("pipeline_error", phase=4, agent="youtube",
                       error=f"Disk full — can't write video file. Free up space and resume. Details: {_err_msg[:200]}")
        elif "executable" in _low or "not found" in _low or "winerror 2" in _low:
            emit_event("pipeline_error", phase=4, agent="youtube",
                       error=f"ffmpeg not found on PATH. Install ffmpeg and retry. Details: {_err_msg[:200]}")
        else:
            emit_event("pipeline_error", phase=4, agent="youtube",
                       error=f"ffmpeg crashed: {_err_msg[:200]}")
        return {"youtube_url": ""}

    # Upload to YouTube
    log("Uploading to YouTube (unlisted)...")
    emit_event("agent_progress", phase=4, agent="youtube",
               status="opening_studio",
               progress="Opening YouTube Studio…")
    page = await browser.new_tab("https://studio.youtube.com")
    await asyncio.sleep(4)

    # Early HV check — YouTube Studio can throw Google's account-challenge
    # interstitial on fresh tabs, especially after fingerprint drift. CUA
    # can't fight past that automatically, so pause early for the user.
    if cua_client:
        cleared = await check_hv_gate(browser, cua_client, "youtube", "YouTube Studio",
                                       phase=5, verbose=verbose)
        if not cleared:
            log("Phase 5: HV gate on YouTube Studio could not be cleared — aborting upload", "ERROR")
            emit_event("pipeline_error", phase=5, agent="youtube",
                       error="youtube_hv_unresolved",
                       reason="YouTube Studio is showing a human-verification challenge we couldn't clear. Resolve it in the browser and retry.")
            return {"youtube_url": ""}

    # Queue video first, then thumbnail for sequential file dialogs
    browser.set_upload_file(str(video_path))
    if title_card.exists():
        browser.queue_upload_file(str(title_card))

    # Use the smart title (matches NotebookLM + email subject for consistency)
    title = smart_title(topic)
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

    emit_event("agent_progress", phase=4, agent="youtube",
               status="uploading",
               progress=f"Uploading video '{title}' to YouTube (unlisted)…")
    _stop, _task = start_narration_ticker(
        4, "youtube",
        f"Uploading '{title}' to YouTube Studio (unlisted)",
        interval=20, expected_minutes=8)
    try:
        result = await agent_loop(cua_client, browser, PROMPT_YOUTUBE_UPLOAD,
            f'Upload video. Title: "{title}"\nDescription:\n{description}\n\n'
            f'All file dialogs are auto-handled (video first, then thumbnail).',
            model=CUA_MODEL, max_iterations=35, verbose=verbose)
    finally:
        await stop_narration_ticker(_stop, _task)

    browser.clear_upload_file()

    # ── C3.5: Blocker recovery — fires only if the primary upload didn't reach
    # "uploaded:" state. Tries to dismiss/retry/fill obstructing dialogs OR
    # declares a clear "upload blocked: <category>" status the orchestrator can
    # surface. Skipped on success so we don't burn CUA budget on clean runs.
    _upload_text = (result.get("text") or "").lower() if isinstance(result, dict) else ""
    if "uploaded:" not in _upload_text and "https://youtu.be/" not in _upload_text:
        try:
            log("[YouTube] Primary upload didn't confirm 'uploaded:' — running blocker recovery")
            emit_event("agent_progress", phase=4, agent="youtube",
                       status="recovering",
                       progress="YouTube upload didn't confirm — running blocker recovery…")
            _stop_r, _task_r = start_narration_ticker(
                4, "youtube",
                "Diagnosing & recovering from YouTube upload blocker",
                interval=20)
            try:
                recovery = await agent_loop(cua_client, browser, PROMPT_RECOVER_YOUTUBE_BLOCKER,
                    f'The prior upload attempt for "{title}" did not confirm success. '
                    f'Diagnose what is blocking, recover if possible, or declare blocked.',
                    model=CUA_MODEL, max_iterations=15, verbose=verbose)
            finally:
                await stop_narration_ticker(_stop_r, _task_r)
            _rec_text = (recovery.get("text") or "") if isinstance(recovery, dict) else ""
            if "uploaded:" in _rec_text.lower() or "https://youtu.be/" in _rec_text.lower():
                log("[YouTube] Blocker recovery succeeded — upload completed")
                result = recovery
            elif "upload blocked:" in _rec_text.lower():
                log(f"[YouTube] Blocker recovery declared blocked — surfacing: "
                    f"{_rec_text.split('upload blocked:', 1)[-1].strip()[:200]}", "WARN")
            else:
                log("[YouTube] Blocker recovery returned ambiguous status — falling through to DOM safety net", "WARN")
        except Exception as _re:
            log(f"[YouTube] Blocker recovery skipped: {_re}", "DEBUG")

    # ── C4: DOM safety net — ensure Unlisted + Not-for-kids before Save ──
    # CUA sometimes misses the radio clicks or the Save button. This block:
    #   1. Ticks "Unlisted" if visibility page is open and no radio is selected.
    #   2. Ticks "No, it's not made for kids" if still on Details page.
    #   3. Clicks Save/Publish if it wasn't already.
    await asyncio.sleep(2)
    try:
        save_status = await page.evaluate("""() => {
            const result = { actions: [], saved: false };
            const text = document.body.innerText.toLowerCase();
            // Already done?
            if (text.includes('video published') || text.includes('video is being processed') ||
                text.includes('processing will begin') || text.includes('your video is live')) {
                result.saved = 'already_saved';
                return result;
            }
            // Ensure "Unlisted" radio is selected (visibility page)
            const radios = document.querySelectorAll('tp-yt-paper-radio-button, [role="radio"]');
            let unlistedSelected = false;
            for (const r of radios) {
                const label = (r.innerText || r.getAttribute('aria-label') || '').toLowerCase();
                const checked = r.getAttribute('aria-checked') === 'true' || r.hasAttribute('checked');
                if (label.includes('unlisted') && checked) { unlistedSelected = true; break; }
            }
            if (!unlistedSelected) {
                for (const r of radios) {
                    const label = (r.innerText || r.getAttribute('aria-label') || '').toLowerCase();
                    if (label.includes('unlisted') && r.offsetParent !== null) {
                        r.click(); result.actions.push('clicked_unlisted'); unlistedSelected = true; break;
                    }
                }
            }
            // Ensure "Not made for kids" radio is selected (details page or MFK dialog)
            let mfkSelected = false;
            for (const r of radios) {
                const label = (r.innerText || r.getAttribute('aria-label') || '').toLowerCase();
                const checked = r.getAttribute('aria-checked') === 'true' || r.hasAttribute('checked');
                if ((label.includes("not made for kids") || label.includes("not for kids") ||
                     label.includes("no, it's not")) && checked) { mfkSelected = true; break; }
            }
            if (!mfkSelected) {
                for (const r of radios) {
                    const label = (r.innerText || r.getAttribute('aria-label') || '').toLowerCase();
                    if ((label.includes("not made for kids") || label.includes("not for kids") ||
                         label.includes("no, it's not")) && r.offsetParent !== null) {
                        r.click(); result.actions.push('clicked_not_for_kids'); mfkSelected = true; break;
                    }
                }
            }
            // Click Save / Publish / Done
            const btns = document.querySelectorAll('button, ytcp-button');
            for (const b of btns) {
                const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                if ((txt === 'save' || txt === 'publish' || txt === 'done') && !b.disabled) {
                    b.click(); result.actions.push('clicked_save'); result.saved = 'clicked_save';
                    return result;
                }
            }
            result.saved = 'no_save_btn';
            return result;
        }""") or {}
        actions = save_status.get('actions', []) if isinstance(save_status, dict) else []
        saved = save_status.get('saved') if isinstance(save_status, dict) else save_status
        for a in actions:
            log(f"[YouTube] DOM safety net: {a}")
        if saved == 'clicked_save':
            log("[YouTube] DOM safety net: clicked Save button")
            await asyncio.sleep(3)
        elif saved == 'already_saved':
            log("[YouTube] Video already saved/published")
    except Exception as e:
        log(f"[YouTube] Save verification: {e}", "WARN")

    # Extract REAL YouTube video URL — NEVER fall back to studio.youtube.com
    emit_event("agent_progress", phase=4, agent="youtube",
               status="processing",
               progress="YouTube is processing the upload — extracting public video URL…")
    await asyncio.sleep(2)
    youtube_url = ""

    # Helper: validate a candidate URL
    def _is_yt_video(u):
        return u and ("youtu.be/" in u or "youtube.com/watch?v=" in u)

    # 1. Check CUA response text for URL
    cua_text = result.get("text", "")
    yt_match = re.search(r'(https?://(?:youtu\.be/|(?:www\.)?youtube\.com/watch\?v=)[a-zA-Z0-9_-]+)', cua_text)
    if yt_match and _is_yt_video(yt_match.group(1)):
        youtube_url = yt_match.group(1)

    # 2. Check DOM for video link in the upload-complete dialog
    if not youtube_url:
        try:
            url = await page.evaluate("""() => {
                // YouTube Studio shows the video link in the publish dialog
                // Check multiple selectors for the video URL
                const selectors = [
                    'a[href*="youtu.be"]',
                    'a[href*="youtube.com/watch"]',
                    'span.video-url-text',
                    '.share-url input',
                    '[class*="video-url"] a',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const href = el.href || el.value || el.innerText || '';
                        if (href.includes('youtu.be/') || href.includes('youtube.com/watch'))
                            return href.trim();
                    }
                }
                // Also check all visible text for youtu.be links
                const text = document.body.innerText;
                const m = text.match(/https?:\\/\\/(?:youtu\\.be\\/|(?:www\\.)?youtube\\.com\\/watch\\?v=)[a-zA-Z0-9_-]+/);
                return m ? m[0] : '';
            }""")
            if _is_yt_video(url):
                youtube_url = url
        except Exception:
            pass

    # 3. Check clipboard
    if not youtube_url:
        clip = get_clipboard()
        if _is_yt_video(clip):
            youtube_url = clip

    # 4. CUA retry — ask it to find and copy the video URL from the dialog
    if not youtube_url:
        log("[YouTube] URL not found in first pass — CUA retry to find video link")
        retry = await agent_loop(cua_client, browser, SYSTEM_BASE + """
Your task: Find the YouTube video URL from the upload completion dialog.

Look for:
1. A video link that starts with youtu.be/ or youtube.com/watch?v=
2. It's usually shown in a dialog after the video is published/saved
3. There might be a "Copy" button next to it — click it
4. If you see a share link or video link, read it and tell me the EXACT URL

ONLY report URLs that start with https://youtu.be/ or https://youtube.com/watch?v=
Do NOT report studio.youtube.com URLs — those are NOT video links.""",
            "Find and tell me the exact YouTube video URL (youtu.be/... or youtube.com/watch?v=...). Click Copy if available.",
            model=CUA_MODEL, max_iterations=8, verbose=verbose)
        retry_text = retry.get("text", "")
        m = re.search(r'(https?://(?:youtu\.be/|(?:www\.)?youtube\.com/watch\?v=)[a-zA-Z0-9_-]+)', retry_text)
        if m and _is_yt_video(m.group(1)):
            youtube_url = m.group(1)
        # Also re-check clipboard after CUA clicked copy
        if not youtube_url:
            clip = get_clipboard()
            if _is_yt_video(clip):
                youtube_url = clip

    # STRICT: Never emit studio.youtube.com or other non-video URLs
    if youtube_url and not _is_yt_video(youtube_url):
        log(f"[YouTube] REJECTED non-video URL: {youtube_url}", "WARN")
        youtube_url = ""

    if youtube_url:
        log(f"YouTube video URL: {youtube_url}")
        # Emit link immediately — frontend shows it without waiting for phase end
        emit_validated_link(4, "youtube", youtube_url, "YouTube Video")
    else:
        log("[YouTube] Could not extract video URL — no link will be emitted", "WARN")
        # Narrate the upload / URL-extract failure. Could be quota, auth
        # (Studio re-login required), or just a rare DOM timing gap where
        # CUA couldn't read the share dialog. extract_with_retry further
        # upstream gets the final word (3× retry → pipeline_error halt).
        try:
            emit_event("pipeline_warning", phase=4, agent="youtube",
                       message="YouTube upload completed but video URL couldn't be extracted",
                       details="Possible causes: YouTube Studio auth expired, upload quota hit, or the publish dialog timed out. The orchestrator will run a 3× extractor retry next; if that also fails the pipeline halts with a clear error.",
                       alertType="warn")
        except Exception:
            pass
    save_track("Phase5", {"status": "youtube_uploaded" if youtube_url else "youtube_url_failed",
                          "youtube_url": youtube_url})

    # Keep all generated files (audio, video, thumbnail) — used by web app
    log(f"Files preserved in queue: {queue_dir}")

    return {"youtube_url": youtube_url}


# ── Phase 6: Google Doc + Gmail Delivery ─────────────────────────────────────

async def run_phase5(browser, cua_client, topic, links, notebook_url, youtube_url,
                     brief_url="", audio_url="", email=None, verbose=False):
    """Phase 5: Create + fill + publicly share Google Doc, then send email with Open Gmail link."""
    log("=" * 60)
    log("PHASE 5: Doc + Email Delivery")
    log("=" * 60)

    # Build doc content — structured format matching PRD.
    #
    # 2026-04-25 (Commit 14): prefer _runtime.agent_share_urls[name] over the
    # `links` arg. The inline share-link extractor in extract_and_record_agent
    # (Commit 11) populates agent_share_urls with public-share URLs when the
    # public toggle succeeded, or the conversation URL as a silent fallback.
    # Either way, the URL stashed there is the one we want in the Doc — it's
    # newer/canonical and carries verification state. The legacy `links` arg
    # is the conversation URL captured at extraction time and is only used as
    # a final fallback (e.g. for resumed runs where _runtime was reset
    # between phases).
    short_topic = topic[:100] if len(topic) > 100 else topic
    doc_lines = [
        f"{short_topic}",
        "",
        "Links to Researches:",
    ]
    if brief_url:
        doc_lines.append(f"ChatGPT Brief: {brief_url}")
    for name in ["ChatGPT", "Gemini", "Claude"]:
        share = _runtime.agent_share_urls.get(name) or {}
        share_url = share.get("url") or ""
        share_kind = share.get("kind") or ""
        # Fallback chain: _runtime public share → _runtime conversation →
        # legacy `links` arg (conversation captured at extraction time).
        url = share_url or links.get(name, "")
        if not url:
            continue
        # Tag the line so the recipient knows whether the link is a real
        # public share or just the agent's chat URL. Public links are
        # readable by anyone; conversation URLs only by the original
        # signed-in user — important context for an email recipient.
        if share_kind == "public" and share.get("verified"):
            doc_lines.append(f"{name} (public share): {url}")
        elif share_url:
            # _runtime knows this is a conversation-URL fallback.
            doc_lines.append(f"{name} (conversation): {url}")
        else:
            # No _runtime entry — legacy `links` path. Treat as conversation
            # since that's what the legacy arg has historically been.
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

    # Create Google Doc: create → fill → make public → emit link
    log("Creating Google Doc...")
    emit_event("agent_progress", phase=5, agent="gdocs",
               status="creating",
               progress="Opening a new Google Doc…")
    doc_url = ""
    try:
        page = await browser.new_tab("https://docs.google.com/document/create")
        await asyncio.sleep(5)

        emit_event("agent_progress", phase=5, agent="gdocs",
                   status="writing",
                   progress=f"Writing research hub ({len(doc_content)} chars, {len(doc_lines)} lines)…")
        _stop, _task = start_narration_ticker(
            5, "gdocs",
            f"Writing & sharing Google Doc hub ({len(doc_lines)} lines)",
            interval=20, expected_minutes=4)
        try:
            await agent_loop(cua_client, browser, PROMPT_CREATE_DOC,
                f"Type this content into the doc, then share with 'Anyone with link' as Editor:\n\n{doc_content}",
                model=CUA_MODEL, max_iterations=20, verbose=verbose)
        finally:
            await stop_narration_ticker(_stop, _task)
        await asyncio.sleep(2)

        # C5: DOM safety net — ensure the doc is public even if CUA missed the share step
        emit_event("agent_progress", phase=5, agent="gdocs",
                   status="sharing",
                   progress="Setting doc to 'Anyone with the link can edit'…")
        try:
            if await _ensure_gdoc_public(page):
                log("Google Doc public share confirmed via DOM")
            await asyncio.sleep(1)
            # Close any lingering share dialog
            await page.keyboard.press("Escape")
        except Exception as e:
            log(f"[gdoc] DOM safety net error: {e}", "WARN")

        doc_url = await browser.current_url()
        # C5: emit link IMMEDIATELY so the frontend doc-icon dropdown renders
        # the working URL before we move on to Gmail.
        if doc_url and validate_link("gdocs", doc_url):
            emit_validated_link(5, "gdocs", doc_url, "Google Doc Hub")
        log(f"Google Doc: {doc_url}")
        save_track("Phase5", {"status": "doc_created", "doc_url": doc_url})
    except Exception as e:
        log(f"Google Doc error: {e}", "ERROR")
        # Upstream orchestrator still runs extract_with_retry on the doc
        # URL with 3 attempts; surface this as a warning so the user has
        # context on which agent failed. If the retry also fails, the
        # orchestrator emits pipeline_error phase=5 from its halt branch.
        try:
            emit_event("pipeline_warning", phase=5, agent="gdocs",
                       message="Google Doc creation hit an error — orchestrator will retry",
                       details=f"{str(e)[:200]}",
                       alertType="warn")
        except Exception:
            pass

    # Send email
    email_sent = False
    if email:
        log(f"Sending email to {email}...")
        emit_event("agent_progress", phase=5, agent="gmail",
                   status="composing",
                   progress=f"Opening Gmail and composing notification email to {email}…")
        try:
            page = await browser.new_tab("https://mail.google.com")
            await asyncio.sleep(4)

            # Subject uses the smart title so it matches NotebookLM + YouTube.
            subject = f"Research Complete: {smart_title(topic)}"
            body_parts = [f"Research complete: {topic[:200]}\n"]
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

            _stop, _task = start_narration_ticker(
                5, "gmail",
                f"Composing & sending notification email to {email}",
                interval=20)
            try:
                await agent_loop(cua_client, browser, PROMPT_SEND_EMAIL,
                    f"Send email to: {email}\nSubject: {subject}\nBody:\n{body}",
                    model=CUA_MODEL, max_iterations=12, verbose=verbose)
            finally:
                await stop_narration_ticker(_stop, _task)

            email_sent = True
            log("Email sent ✓")
            save_track("Phase5", {"status": "email_sent", "email": email})
            # Emit Gmail link immediately so it shows in the dropdown
            emit_event("link_extracted", phase=5, agent="gmail",
                       url="https://mail.google.com", label="Open Gmail", verified=True)
        except Exception as e:
            log(f"Email error: {e}", "ERROR")
            # Email failure isn't fatal — pipeline is essentially done by
            # this point (doc is shipped). Warn so the user knows they
            # need to open Gmail manually, and distinguish bad-address
            # from SMTP/auth issues so the message is actionable.
            _err_msg = str(e)
            _low = _err_msg.lower()
            if "invalid" in _low and ("address" in _low or "email" in _low or "recipient" in _low):
                _msg = f"Email not sent — recipient address '{email}' looks invalid"
                _det = "Gmail rejected the recipient. Update the email in Settings and re-send manually, or resume with a corrected address."
            elif "auth" in _low or "login" in _low or "signin" in _low:
                _msg = "Email not sent — Gmail login expired"
                _det = "Re-authenticate Gmail in the browser and resume to retry, or send the notification manually."
            else:
                _msg = "Email not sent — SMTP/Gmail error"
                _det = f"{_err_msg[:200]}"
            try:
                emit_event("pipeline_warning", phase=5, agent="gmail",
                           message=_msg, details=_det, alertType="warn")
            except Exception:
                pass
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
    # Phase 2 done → resume from Phase 3 ONLY if the Phase-2 completion
    # marker is present. The marker is written after the round-robin poller
    # returned (i.e. all agents reached a terminal state). Without the
    # marker, "any non-brief MD >100 bytes" was too coarse — a backend crash
    # mid-P2 with only one agent's MD on disk would falsely jump to Phase 3,
    # silently skipping the agents that hadn't finished yet.
    marker = queue_dir / "phase2_complete.marker"
    if marker.exists():
        return 3, "Phase 2 complete marker present — resuming from Phase 3"
    # No marker but some MDs on disk → P2 was interrupted. Restart Phase 2
    # so the unfinished agents complete. NOTE: re-running P2 re-extracts
    # ALL enabled agents from scratch (`run_phase2` doesn't currently scan
    # disk to skip already-finished agents). Existing MDs are overwritten
    # via the Firestore upsert in `save_document_to_firestore`. Wasteful
    # on time but safe — the only correctness cost is a few extra minutes
    # of agent work; data-wise the new MDs are at least as good as the
    # old. An idempotency guard ("if documents/{agent}.md exists, skip
    # launching") would be a real refactor, not landed here.
    research_dir = queue_dir / "documents"
    has_partial_research = research_dir.exists() and any(
        f for f in research_dir.glob("*.md") if f.stat().st_size > 100 and f.stem != "brief")
    if has_partial_research:
        return 2, "Phase 2 partial MDs present without completion marker — re-running Phase 2 (all agents)"
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
                       run_id=None, uid=None, research_id=None, brief_text=""):
    """Run the full pipeline. Supports resume from a previous queue directory.

    brief_text (2026-04): inline brief content passed from the frontend when
    the user toggled Phase 1 off. Written to the new run's
    queues/<run>/documents/brief.md before Phase 1 decides its path; this
    makes `brief_file` point at the fresh file and flows through the
    `_brief_from_file` branch, skipping ChatGPT brief generation + share-link
    extraction."""
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
        setup_firestore_run(uid, research_id or run_id, asyncio.get_running_loop(), run_id=run_id)
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
        # Inline brief → persist as the new run's brief.md, then route the
        # pipeline through brief_file so Phase 1 lands on the `_brief_from_file`
        # branch (no ChatGPT brief generation, no share-link extraction).
        if brief_text and not brief_file:
            _inline_brief_path = queue_dir / "documents" / "brief.md"
            _inline_md = brief_text if brief_text.lstrip().startswith("# Research Brief") \
                         else f"# Research Brief\n\n{brief_text}"
            _inline_brief_path.write_text(_inline_md, encoding="utf-8")
            brief_file = str(_inline_brief_path)
            log(f"Inline brief persisted ({len(brief_text)} chars) → {_inline_brief_path.name}")

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

    # Stop/pause are driven through `_controls` (asyncio events) now. The
    # .stop and .pause sentinel files are still written by the HTTP endpoints
    # for backward-compat with the resume flow + pipeline_state reporting —
    # no in-pipeline helper needed here.

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

    async def _phase_timeout_decision(phase: int, max_min: int, agent: str | None = None) -> str:
        """Recoverable response to a per-phase active-time ceiling. Per the
        never-die contract, BE-detected stuck phases do NOT terminate the
        run — they emit pipeline_error with [Retry, Skip] actions and pause
        for the user's call. User decides:
          - retry → restore from checkpoint, rerun the phase (fresh deadline)
          - skip  → mark phase done, advance to next
          - stop  → only fires if user explicitly hit Stop (chat input button)
                    while the alert was up; await_phase_decision picks that up
                    via _controls.is_stop()
        Returns the user's decision string. Does NOT write delivery.json
        status="stopped" — that's reserved for terminal stop paths only."""
        log(f"Phase {phase}: active-time ceiling {max_min}min hit — surfacing to user as recoverable error", "WARN")
        actions = [
            {"id": "retry", "label": "Retry from checkpoint", "style": "primary",
             "command": {"action": "retry_phase", "phase": phase}},
            {"id": "skip", "label": "Skip phase", "style": "default",
             "command": {"action": "skip_phase", "phase": phase}},
        ]
        try:
            fail_phase(
                phase=phase,
                error=f"Phase {phase} exceeded {max_min}-minute active-time ceiling",
                reason=(
                    f"This phase has been running for {max_min} minutes of active work "
                    "without completing — likely stuck on a CUA loop, frozen Playwright "
                    "operation, or a platform UI hiccup. Retry restores from the last "
                    "checkpoint and reruns this phase with a fresh budget. Skip moves "
                    "past this phase and continues with whatever artifacts are on disk. "
                    "You can also Stop the pipeline from the chat input bar."
                ),
                agent=agent,
                actions=actions,
            )
        except Exception as _e:
            # fail_phase signature mismatch → fall back to direct emit
            log(f"_phase_timeout_decision: fail_phase fallback ({_e})", "WARN")
            emit_event("pipeline_error", phase=phase, agent=agent,
                       error=f"Phase {phase} exceeded {max_min}-minute active-time ceiling",
                       reason=f"Stuck — Retry from checkpoint or Skip the phase.",
                       actions=actions)
        # Pause flag freezes the active-time clock during the user's
        # decision wait, so a 20-min decision delay doesn't burn budget
        # against the next retry. Also flips the FE chat input to paused.
        _controls.request_pause()
        emit_event("pipeline_paused", phase=phase, reason="phase_timeout")
        decision = await _controls.await_phase_decision(phase)
        emit_event("pipeline_resumed", phase=phase, reason=f"phase_timeout_{decision}")
        return decision

    async def _await_phase_with_active_deadline(phase: int, max_min: int, coro_factory):
        """Run a phase coroutine factory with an ACTIVE-TIME wall-clock
        deadline. Time spent while `_controls.is_pause()` is True does NOT
        count toward the budget — so a user pausing for an hour doesn't
        kill a healthy phase. Cancels the coroutine when active-time
        exhausts and raises asyncio.TimeoutError. The caller catches it,
        runs `_phase_timeout_decision` to give the user Retry/Skip, and
        on Retry calls this helper AGAIN (factory creates a fresh coro).

        coro_factory is `Callable[[], Coroutine]` — must produce a fresh
        coroutine on each call so retry doesn't await an already-awaited
        coroutine. Tick is 5s — fine-grained enough for any budget."""
        run_task = asyncio.ensure_future(coro_factory())
        active_sec = 0.0
        deadline_sec = float(max_min * 60)
        tick = 5.0
        while not run_task.done():
            try:
                await asyncio.sleep(tick)
            except asyncio.CancelledError:
                run_task.cancel()
                raise
            # User-Stop short-circuit: the deadline loop used to ignore the
            # Stop button and only react when the phase coroutine itself
            # noticed the stop flag — which could be deep inside a long
            # CUA call. Now we cancel-and-propagate immediately, so user
            # Stop during a stuck phase exits within one tick (5s) instead
            # of waiting up to `max_min` for the deadline.
            if _controls.is_stop():
                run_task.cancel()
                try: await run_task
                except BaseException: pass
                raise asyncio.CancelledError(f"phase {phase} stopped by user")
            if not _controls.is_pause():
                active_sec += tick
            if active_sec >= deadline_sec and not run_task.done():
                log(f"Phase {phase}: active-time {active_sec:.0f}s exceeded {deadline_sec:.0f}s — cancelling for user decision", "WARN")
                run_task.cancel()
                # CancelledError inherits from BaseException (not Exception)
                # since Python 3.8, so `except Exception: pass` did NOT catch
                # the post-cancel re-raise — and the `raise TimeoutError`
                # below was never reached. Catching BaseException converts
                # the cancel into the TimeoutError the retry loop expects.
                try: await run_task
                except BaseException as _drained:
                    # DEBUG-log the drained class so any future regression
                    # where something unexpected leaks (custom exception,
                    # SystemExit, etc.) doesn't go silent.
                    log(f"Phase {phase}: drained {type(_drained).__name__} post-cancel", "DEBUG")
                raise asyncio.TimeoutError(
                    f"phase {phase} exceeded {max_min}-min active-time budget"
                )
        return await run_task

    # Create delivery.json immediately (frontend can see the run from the start)
    if not (queue_dir / "delivery.json").exists():
        update_delivery()

    browser = Browser(PROFILE_DIR, headless=False)
    try:
        # ══════════════════════ PHASE 0: Preflight ══════════════════════
        # Phase 0 does real work now: launch browser, verify each platform's
        # login session, check env dependencies (Gemini key, ffmpeg). If any
        # platform is not logged in, emit `login_required` and pause the
        # pipeline — frontend shows a sticky banner with Retry.
        emit_event("phase_start", phase=0, description="Verifying environment + logins")
        _update_firestore_research({"phase": 0, "currentPhase": 0, "status": "ongoing"})
        _p0_start = time.time()

        emit_event("agent_progress", phase=0, agent="system", status="Launching",
                   progress="Starting Chromium browser with automation profile…")
        # ARCHITECTURE 2026-04-18 (never-die): browser-launch failures are
        # user-recoverable (close other Chrome, run `playwright install`,
        # etc.). Retry re-invokes browser.start() in-place; Stop ends the
        # run. Skip isn't offered — every downstream phase needs a working
        # browser, so skipping Phase 0 is meaningless.
        while True:
            try:
                await browser.start()
                break
            except Exception as _launch_err:
                # Most common launch failures:
                #   • Profile locked by another running Chrome instance →
                #     SingletonLock couldn't be removed (another Playwright run)
                #   • Playwright not installed → `playwright install chromium` missing
                #   • Chromium binary missing / corrupt
                _err_msg = str(_launch_err)
                _low = _err_msg.lower()
                if "profile" in _low and ("lock" in _low or "in use" in _low or "singleton" in _low):
                    _friendly = f"Chrome profile is locked by another session. Close any running automation browsers (or previous pipeline runs), then click Retry."
                elif "executable" in _low or "chromium" in _low or "browser" in _low:
                    _friendly = f"Browser binary missing or failed to start. Run `playwright install chromium`, then click Retry."
                else:
                    _friendly = f"Browser launch failed: {_err_msg[:200]}"
                log(f"Phase 0 browser launch failed: {_err_msg[:200]} — awaiting user decision", "ERROR")
                fail_phase(
                    phase=0,
                    error=f"Browser launch failed: {_err_msg[:200]}",
                    reason=_friendly,
                    agent="system",
                    actions=[
                        {"id": "retry", "label": "Retry", "style": "primary",
                         "command": {"action": "retry_phase", "phase": 0}},
                    ],
                )
                decision = await _controls.await_phase_decision(0)
                if decision == "retry":
                    log("Phase 0 browser launch: user requested retry", "INFO")
                    emit_event("phase_restart", phase=0, reason="user_retry_browser_launch", attempt=0)
                    continue
                # skip (not offered but handled defensively) / stop / timeout
                log(f"Phase 0 browser launch: user {decision} — terminating pipeline", "INFO")
                emit_event("pipeline_stopped", phase=0, reason=f"user_{decision}_browser_launch")
                return

        # Build list of platforms to verify based on enabled agents + phases
        _agents_cfg = config.get("agents", {}) if isinstance(config, dict) else {}
        _need_chatgpt = _agents_cfg.get("chatgpt", True)
        _need_gemini = _agents_cfg.get("gemini", True)
        _need_claude = _agents_cfg.get("claude", True)
        _need_notebooklm = 3 not in skip_phases
        _need_youtube = 4 not in skip_phases and config.get("videoEnabled", True) if isinstance(config, dict) else 4 not in skip_phases
        _need_gmail = 5 not in skip_phases and config.get("emailEnabled", True) if isinstance(config, dict) else 5 not in skip_phases
        _need_gdocs = 5 not in skip_phases

        preflight_platforms = []
        if _need_chatgpt:    preflight_platforms.append(("ChatGPT", "chatgpt"))
        if _need_gemini:     preflight_platforms.append(("Gemini", "gemini"))
        if _need_claude:     preflight_platforms.append(("Claude", "claude"))
        if _need_notebooklm: preflight_platforms.append(("NotebookLM", "notebooklm"))
        if _need_youtube:    preflight_platforms.append(("YouTube Studio", "youtube"))
        if _need_gmail:      preflight_platforms.append(("Gmail", "gmail"))
        if _need_gdocs:      preflight_platforms.append(("Google Docs", "gdocs"))

        # Honor the user's preference (global Settings → Pipeline → Skip
        # login verification, plus any per-run override in pipeline_config).
        # When on, we skip the per-platform CUA round entirely: browser is
        # already running, Phase 1 will navigate itself to ChatGPT.
        _skip_verify_pref = bool(pipeline_config.get("skipInitVerify", False)) if isinstance(pipeline_config, dict) else False
        if _skip_verify_pref:
            log("Phase 0: skipInitVerify=true — bypassing login verification per user pref", "INFO")
            emit_event("agent_progress", phase=0, agent="system", status="Skipped",
                       progress="Login verification skipped (per your pipeline settings)")
            preflight_platforms = []  # Nothing to verify below — while loop skipped

        # SEQUENTIAL-2026-04-19: walk platforms one at a time. Old flow
        # opened all 7 tabs in a loop before surfacing a single bulk
        # login_required — that's (a) a Cloudflare-visible robotic burst
        # and (b) overwhelming for the user, who now has to juggle 7
        # partial login flows simultaneously. New flow: cookie-check
        # first, tab-open only on miss, CUA-verify, and if STILL not
        # logged in, emit `login_required` scoped to THAT platform and
        # wait for user retry before touching the next one. This mirrors
        # how the --pair script already walks setup Step 2.
        label_by_key = {key: label for label, key in preflight_platforms}
        _preflight_tabs: dict[str, object] = {}
        _pf_opened = 0  # Counts real tab-opens across the whole sequence for stagger pacing
        _global_skip = False
        for idx, (label, key) in enumerate(preflight_platforms):
            if _global_skip or _controls.skip_init_verify:
                _global_skip = True
                log(f"Phase 0: SKIP_INIT_VERIFY — skipping remaining platform {label}", "INFO")
                continue
            attempt = 0
            while True:
                attempt += 1
                if _controls.skip_init_verify:
                    _global_skip = True
                    break
                # NOTE (2026-04-24 #2): cookie + Playwright pre-checks both
                # removed. Cookies lie when the session is server-side
                # invalidated but the cookie hasn't expired yet; Playwright
                # strict DOM selectors match cached sidebar fragments on
                # ChatGPT's logged-out landing (and probably other
                # platforms' skeleton UIs too). Both gave us speed but let
                # false positives through, which was tolerable only until
                # we removed the per-phase login probe safety net — now
                # Phase 0 is the only gate, and it must not lie.
                #
                # Flow below: tab open → 4s settle → URL check → CUA.
                # Vision is the single source of truth. Slower (~5-10s per
                # platform × up to 7 = ~1 min worst case on cold starts)
                # but it actually looks at what's on screen. Not a
                # performance win we can afford to keep taking.
                # STEALTH-2026-04-19: jitter between cold-start tab opens.
                # Back-to-back opens in <2s are a strong robotic signal.
                if _pf_opened > 0 and key not in _preflight_tabs:
                    await asyncio.sleep(random.uniform(2.5, 4.5))
                log(f"Phase 0: checking {label} (attempt {attempt})", "INFO")
                emit_event("agent_progress", phase=0, agent=key, status="checking",
                           progress=f"Verifying {label} login…")
                try:
                    info = LOGIN_PLATFORMS.get(key)
                    root = info["root"] if info else "about:blank"
                    tab = _preflight_tabs.get(key)
                    if tab is None:
                        tab = await browser.new_tab(root)
                        _pf_opened += 1
                        _preflight_tabs[key] = tab
                    else:
                        # Retry path — re-navigate so we pick up new login state.
                        try:
                            await tab.goto(root, wait_until="domcontentloaded", timeout=15000)
                        except Exception:
                            pass
                    # Settle for SPA hydration — Claude.ai / Google Docs paint a
                    # neutral "loading" shell for 3-4s that CUA misreads as a
                    # login wall if we peek too early.
                    await asyncio.sleep(4.0)
                    # Cheap negative signal first: URL on a known login host →
                    # definitely logged out. Skip the CUA call to save budget.
                    try:
                        current_url = (tab.url or "").lower()
                    except Exception:
                        current_url = ""
                    if any(h in current_url for h in _LOGIN_HOST_NEGATIVES):
                        log(f"Phase 0: {label} on login URL ({current_url[:60]}) — not logged in", "INFO")
                        ok = False
                    else:
                        # Vision verification is the gate. URL already
                        # cleared the cheap "obvious login wall" case;
                        # everything else is a CUA decision.
                        ok = await verify_login_cua(tab, key, cua_client)
                except CuaUnavailableError as cua_err:
                    # Structural Anthropic failure (billing cap / invalid
                    # key / 529). Surface a distinct alert so the user
                    # doesn't chase a phantom auth issue. Default actions:
                    # skip this platform (proceed with remaining) or stop.
                    log(f"Phase 0: CUA unavailable for {label}: {cua_err}", "ERROR")
                    emit_event("pipeline_error", phase=0, agent=key,
                               error="cua_unavailable",
                               reason=f"CUA vision check can't run: {str(cua_err)[:180]}",
                               details="Raise the Anthropic workspace cap, swap CUA_API_KEY, or skip remaining verification.",
                               actions=[
                                   {"id": "skip", "label": "Skip verification", "style": "default",
                                    "command": {"action": "skip_init_verify"}},
                                   {"id": "retry", "label": "Retry", "style": "primary",
                                    "command": {"action": "retry_phase", "phase": 0}},
                               ])
                    _controls.request_pause()
                    emit_event("pipeline_paused", phase=0, reason="cua_unavailable")
                    await _controls.wait_if_paused()
                    if _controls.is_stop():
                        emit_event("pipeline_stopped", phase=0, reason="stopped during cua_unavailable")
                        return
                    if _controls.skip_init_verify:
                        log(f"Phase 0: SKIP_INIT_VERIFY during {label} (CUA unavailable) — skipping remaining", "INFO")
                        _global_skip = True
                        break
                    # retry — clear flag + loop continues, cookie probe runs again
                    _controls.consume_retry_phase(0)
                    _controls.retry_init_verify = False
                    continue
                except Exception as e:
                    log(f"Phase 0: login check failed for {key}: {e}", "WARN")
                    ok = False

                if ok:
                    emit_event("agent_progress", phase=0, agent=key,
                               status="ok", progress=f"{label}: logged in ✓")
                    break  # move to next platform

                # Not logged in — emit login_required scoped to JUST this
                # platform and wait for user retry.
                emit_event("agent_progress", phase=0, agent=key,
                           status="needs_login", progress=f"{label}: login required ✗")
                emit_event("login_required",
                           phase=0,
                           platforms=[key],
                           platformLabels=[label],
                           machineName=socket.gethostname(),
                           attempt=attempt,
                           message=f"Log into {label} in the browser on your setup PC.")
                _controls.request_pause()
                emit_event("pipeline_paused", phase=0, reason="login_required")
                await _controls.wait_if_paused()
                if _controls.is_stop():
                    emit_event("pipeline_stopped", phase=0, reason="stopped during login_required")
                    return
                if _controls.skip_init_verify:
                    log(f"Phase 0: SKIP_INIT_VERIFY during {label} — skipping remaining platforms", "INFO")
                    _global_skip = True
                    break
                # Unify retry signals: the login_required banner's dedicated
                # "Retry" button writes action="retry_init_verify", but the
                # generic PhaseAlertPanel Retry button writes action="retry_phase"
                # with phase=0. Both mean the same thing here — the user
                # acted in the browser, re-check this platform with fresh state.
                if _controls.consume_retry_phase(0):
                    _controls.retry_init_verify = True
                _is_retry = bool(_controls.retry_init_verify)
                emit_event("pipeline_resumed", phase=0, reason="retry" if _is_retry else "resume")
                # Always close the tab on resume. The user just did something
                # in the browser (logged in, solved a CAPTCHA, dismissed a
                # popup) — re-using the stale tab would make the next CUA
                # screenshot identical to the pre-pause one, defeating the retry.
                _t = _preflight_tabs.pop(key, None)
                if _t is not None:
                    try: await _t.close()
                    except Exception: pass
                if _is_retry:
                    _controls.retry_init_verify = False
                    emit_event("phase_start", phase=0,
                               description=f"Re-checking {label} (attempt {attempt + 1})")
                    _update_firestore_research({"phase": 0, "currentPhase": 0, "status": "ongoing"})
                log(f"Phase 0: resumed ({'retry' if _is_retry else 'resume'}) — re-checking {label}", "INFO")
                # while loop continues — re-check same platform with fresh state
            # Inner while exited — either verified, skipped globally, or stopped.
            if _global_skip:
                emit_event("agent_progress", phase=0, agent="system", status="Skipped",
                           progress="Verification skipped by user")
                break  # break outer for

        # Env checks: Gemini key for nano-banana thumbnail + ffmpeg for video.
        # Run these regardless of whether login verification was skipped —
        # missing env breaks phase 4 whether or not logins are verified.
        _env_ok = True
        _env_errors: list[str] = []
        if _need_youtube:
            if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
                _env_ok = False
                _env_errors.append("GOOGLE_API_KEY / GEMINI_API_KEY missing (needed for thumbnail)")
            if not shutil.which("ffmpeg"):
                _env_ok = False
                _env_errors.append("ffmpeg not on PATH (needed for video encoding)")
        if not _env_ok:
            emit_event("login_required",
                       phase=0,
                       platforms=[],
                       platformLabels=[],
                       machineName=socket.gethostname(),
                       envErrors=_env_errors,
                       attempt=1,
                       message="Environment check failed — see errors above.")
            _controls.request_pause()
            emit_event("pipeline_paused", phase=0, reason="login_required")
            await _controls.wait_if_paused()
            if _controls.is_stop():
                emit_event("pipeline_stopped", phase=0, reason="stopped during env_error")
                return
            emit_event("pipeline_resumed", phase=0, reason="retry")

        # Close the preflight verification tabs so they don't clutter the
        # window through Phases 1-5. CRITICAL: Browser.new_tab() reassigns
        # self.page to each new tab, so `browser.page` is the LAST preflight
        # tab we opened. Phase 1 navigates `browser.page` to ChatGPT — we
        # must KEEP that page alive. So: close every preflight tab EXCEPT
        # whichever one is currently browser.page. Phase 1's navigate() will
        # then reuse that page as its ChatGPT tab.
        primary = browser.page
        for _key, _tab in _preflight_tabs.items():
            if _tab is primary:
                continue
            try:
                await _tab.close()
            except Exception:
                pass
        _preflight_tabs.clear()

        if _skip_verify_pref or _controls.skip_init_verify:
            _p0_summary = "Preflight skipped — trusting existing sessions"
        elif preflight_platforms:
            _p0_summary = f"Preflight passed — {len(preflight_platforms)} platform(s) ready"
        else:
            _p0_summary = "Preflight complete"
        emit_event("phase_complete", phase=0,
                   durationSec=int(time.time() - _p0_start),
                   summary=_p0_summary)

        # ══════════════════════ PHASE 1: Brief ══════════════════════
        p1 = None
        _user_skip_p1 = _controls.consume_phase_skip(1)
        if 1 in skip_phases or _user_skip_p1:
            _reason = "user_skip" if _user_skip_p1 else "Disabled in pipeline config"
            log(f"Phase 1: SKIPPED ({_reason})")
            emit_event("phase_skipped", phase=1, reason=_reason)
            # Phase-1-skip must still hydrate brief_text so Phase 2 has a
            # brief to paste. Priority: explicit brief_file > on-disk
            # documents/brief.md (written by the inline-brief path earlier,
            # or by a previous run we're resuming). Phase 2 hard-fails
            # without this ("No brief text available — cannot run Phase 2").
            _loaded_from = None
            if brief_file and Path(brief_file).exists():
                try:
                    brief_text = Path(brief_file).read_text(encoding="utf-8")
                    _loaded_from = f"brief_file={brief_file}"
                except Exception as _e:
                    log(f"Phase 1 skip: could not read brief_file ({_e})", "WARN")
            if not brief_text:
                for _bp in [queue_dir / "documents" / "brief.md", queue_dir / "brief.md"]:
                    if _bp.exists():
                        try:
                            brief_text = _bp.read_text(encoding="utf-8")
                            _loaded_from = f"disk={_bp}"
                            break
                        except Exception:
                            continue
            if brief_text.startswith("# Research Brief\n\n"):
                brief_text = brief_text[len("# Research Brief\n\n"):]
            brief_artifact = BriefArtifact(text=brief_text, url="")
            if brief_text:
                log(f"Phase 1 skip: loaded brief ({len(brief_text)} chars) from {_loaded_from}")
            else:
                log("Phase 1 skip: no brief source — Phase 2 will fail unless one appears", "WARN")
        elif start_phase <= 1:
            emit_event("phase_start", phase=1, description="Generating research brief with ChatGPT Pro + Extended Thinking", agents=["chatgpt"])
            _update_firestore_research({"phase": 1, "currentPhase": 1, "status": "ongoing"})
            _p1_start = time.time()
            # Active-time ceiling for Phase 1 — paused seconds don't count.
            # If the user pauses for lunch, the budget is preserved.
            # Enforced via _await_phase_with_active_deadline at each call
            # below; budget is shared across the for _p1_attempt restart loop.
            # PHASE_1_MAX_MIN is the cap (env-overridable).
            # Per-phase login probe removed (2026-04-24). Phase 0 is now
            # the single source of truth for login state — if Phase 0
            # marked a platform "ok" (cookie + DOM or CUA verdict), we
            # trust it and proceed. On real session drift mid-run, the
            # phase's own navigation + scraping will surface a real
            # failure through fail_phase, which the alert panel handles.
            # ARCHITECTURE 2026-04-18: Never-die retry loop. Any fail_phase
            # inside this block awaits the user's Retry/Skip/Stop decision
            # via _controls.await_phase_decision(1). Retry loops back; Skip
            # breaks out with brief_text="" so downstream phases can decide
            # what to do with no brief; Stop returns from the pipeline.
            _p1_skipped_after_error = False
            _brief_from_file = False
            while True:
                if brief_file:
                    brief_text = Path(brief_file).read_text(encoding="utf-8")
                    # Strip the common "# Research Brief\n\n" prefix if present so
                    # downstream token counts / paste ops aren't inflated by it.
                    if brief_text.startswith("# Research Brief\n\n"):
                        brief_text = brief_text[len("# Research Brief\n\n"):]
                    log(f"Phase 1: SKIPPED — loaded brief from {brief_file} ({len(brief_text)} chars)")
                    brief_url = ""
                    _brief_from_file = True
                    break
                fb1 = get_feedback(1)
                # Restart loop: if mid-phase pause+input+resume trips
                # `_runtime.restart_requested`, merge the buffered context into
                # the topic and rerun Phase 1. Capped at 3 attempts.
                p1 = None
                current_topic = topic
                for _p1_attempt in range(3):
                    _runtime.restart_requested = False
                    # Inner timeout-retry loop: if the active-time ceiling
                    # fires, surface to user with [Retry, Skip] (recoverable),
                    # NOT terminate the run. lambda factory creates a fresh
                    # coroutine on each retry — can't await an already-awaited
                    # coroutine, so the helper takes a factory now.
                    while True:
                        try:
                            p1 = await _await_phase_with_active_deadline(
                                1, PHASE_1_MAX_MIN,
                                lambda: run_phase1(browser, cua_client, current_topic, pdf_paths, verbose, feedback=fb1),
                            )
                            break  # success — exit inner retry loop
                        except asyncio.TimeoutError:
                            _decision = await _phase_timeout_decision(1, PHASE_1_MAX_MIN, agent="chatgpt")
                            if _decision == "retry":
                                emit_event("phase_restart", phase=1, reason="user_retry_after_timeout")
                                continue  # rerun via factory with fresh deadline
                            if _decision == "skip":
                                emit_event("phase_skipped", phase=1, reason="user_skip_after_timeout")
                                _p1_skipped_after_error = True
                                p1 = None
                                break
                            # stop / fall-through (user explicitly hit Stop)
                            emit_event("pipeline_stopped", phase=1, reason=f"user_{_decision}_after_timeout")
                            return
                    if _p1_skipped_after_error:
                        break  # exit outer for _p1_attempt loop too
                    if fb1:
                        clear_feedback(1)
                        fb1 = ""  # only feed in on first attempt
                    if not _runtime.restart_requested:
                        break
                    extra_ctx_retry = _controls.pop_extra_context()
                    if not extra_ctx_retry:
                        break
                    current_topic = current_topic + "\n\nADDITIONAL USER CONTEXT:\n" + extra_ctx_retry
                    log(f"[Phase 1] Mid-phase restart with +{len(extra_ctx_retry)} chars of user input")
                    emit_event("phase_restart", phase=1,
                               reason="mid_phase_input_on_resume",
                               chars=len(extra_ctx_retry), attempt=_p1_attempt+1)
                if not p1 or not p1["text"]:
                    log("Phase 1 failed — no brief generated; awaiting user decision", "ERROR")
                    fail_phase(
                        phase=1,
                        error="no brief generated",
                        reason="ChatGPT Pro didn't produce a research brief after all retries. Check the ChatGPT session is signed in, then try again.",
                        agent="chatgpt",
                    )
                    decision = await _controls.await_phase_decision(1)
                    if decision == "retry":
                        log("Phase 1: user requested retry — re-running from the top", "INFO")
                        emit_event("phase_restart", phase=1, reason="user_retry_after_error", attempt=0)
                        continue
                    if decision == "skip":
                        log("Phase 1: user skipped after error — continuing with empty brief", "INFO")
                        emit_event("phase_skipped", phase=1, reason="user_skip_after_error")
                        brief_text = ""
                        brief_url = ""
                        _p1_skipped_after_error = True
                        break
                    # stop / timeout — only way the pipeline actually ends
                    log(f"Phase 1: user {decision} after error — terminating pipeline", "INFO")
                    emit_event("pipeline_stopped", phase=1, reason=f"user_{decision}_after_error")
                    return
                brief_text = p1["text"]
                brief_url = p1.get("url", "")
                break
                # Brief-short acknowledgement: run_phase1 already emitted a
                # pipeline_warning with [continue_anyway] buttons when the
                # brief is 100-500 chars. If the user pressed Continue, the
                # command listener set the flag — consume it here just to
                # clear the state (we proceed regardless). If the user hit
                # Retry, they went through Stop + re-submit, which runs a
                # fresh pipeline entirely.
                if _controls.consume_continue_anyway():
                    log("Phase 1: brief-short warning dismissed by user (continue_anyway)")
            # Save brief in documents/
            if _p1_skipped_after_error:
                # User chose Skip after a brief-generation error — emit a
                # stub phase_complete so the pipeline tile shows the skip
                # outcome instead of hanging, and set brief_artifact to an
                # empty shell so downstream Phase 2 can make its own
                # decision (it has its own fail_phase + await_phase_decision
                # when the paste step finds no content).
                brief_artifact = BriefArtifact(text="", url="")
                emit_event("phase_complete", phase=1, durationSec=int(time.time() - _p1_start),
                    summary="Phase 1 skipped after error — no brief generated")
                _update_firestore_research({"phase": 1, "status": "ongoing"})
            elif _brief_from_file:
                # Phase 1 bypassed via --brief-file (or frontend briefText).
                # Persist to disk + Firestore. The user supplied the text;
                # there's no ChatGPT session to share from. Link to the
                # in-app document viewer (FE Documents page renders the
                # markdown in app theme).
                _brief_md = f"# Research Brief\n\n{brief_text}"
                (queue_dir / "documents" / "brief.md").write_text(_brief_md, encoding="utf-8")
                save_document_to_firestore("brief", _brief_md, "Research Brief")
                _in_app_brief_url = f"/documents?open={_fb_research_id}:brief" if _fb_research_id else "/documents"
                brief_artifact = BriefArtifact(text=brief_text, url=_in_app_brief_url)
                log(f"BriefArtifact (from file): {brief_artifact.chars} chars, "
                    f"{len(brief_artifact.sections)} sections")
                _p1_links = [{"label": "Read brief", "url": _in_app_brief_url, "verified": True, "primary": True}]
                save_checkpoint(queue_dir, 1, topic=topic, brief_url=_in_app_brief_url)
                save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())
                emit_event("phase_complete", phase=1,
                    durationSec=int(time.time() - _p1_start), links=_p1_links,
                    summary=f"Research brief loaded from file ({brief_artifact.chars} chars)")
                _update_firestore_research({"phase": 1, "status": "ongoing", "links.phase1": _p1_links})
            else:
                _brief_md = f"# Research Brief\n\n{brief_text}"
                (queue_dir / "documents" / "brief.md").write_text(_brief_md, encoding="utf-8")
                # Sync to Firestore documents subcollection — this is the
                # source of truth the FE Documents page renders. Phase 2
                # uses brief_artifact.text for paste; the URL is purely for
                # display in the phase dropdown + chat.
                save_document_to_firestore("brief", _brief_md, "Research Brief")
                # ── Markdown-as-primary architecture (2026-04-25) ──
                # phase_complete fires as SOON as the brief markdown is
                # in Firestore. The primary link points at the in-app
                # Documents viewer — guaranteed to work, no platform
                # share-link scraping required. Share-link extraction
                # runs AFTER as a best-effort secondary (90s budget,
                # conversation URL fallback) and lands via link_extracted.
                # Goals: (a) phase_complete is no longer gated on a
                # flaky CUA share-modal flow; (b) the chat/dropdown link
                # always works; (c) the run advances even if ChatGPT's
                # share UI changes overnight.
                _in_app_brief_url = f"/documents?open={_fb_research_id}:brief" if _fb_research_id else "/documents"
                brief_artifact = BriefArtifact(text=brief_text, url=_in_app_brief_url)
                log(f"BriefArtifact: {brief_artifact.chars} chars, {len(brief_artifact.sections)} sections")
                _p1_links = [{"label": "Read brief", "url": _in_app_brief_url, "verified": True, "primary": True}]
                save_checkpoint(queue_dir, 1, topic=topic, brief_url=_in_app_brief_url)
                update_delivery(brief_url=_in_app_brief_url)
                save_meta(queue_dir, topic, 1, summary=brief_text[:200].strip())
                emit_event("phase_complete", phase=1, durationSec=int(time.time() - _p1_start),
                    links=_p1_links,
                    summary=f"Research brief generated ({brief_artifact.chars} chars, {len(brief_artifact.sections)} sections)")
                _update_firestore_research({"phase": 1, "status": "ongoing", "links.phase1": _p1_links})
                # 2026-04-25: P1 secondary "View on ChatGPT" link removed.
                # The in-app /documents?open=…:brief primary is the only link
                # surfaced to the FE. The conversation URL (brief_url, captured
                # at line ~12209) still propagates to Phase 5 for the Google
                # Doc — it just isn't streamed as a separate link_extracted.
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
                # Relaunch browser on resume
                browser = Browser(PROFILE_DIR, headless=False)
                await browser.start()
                emit_event("pipeline_resumed", phase=1)
                _update_firestore_research({"status": "ongoing"})
                # Pause+resume+input semantics: rerun the paused phase with the
                # user's input folded into the combined topic. The resulting
                # brief carries the new guidance forward into Phase 2 naturally.
                if _controls.peek_extra_context():
                    resume_input = _controls.pop_extra_context()
                    log(f"Phase 1 resume-with-input — regenerating brief with {len(resume_input)} extra chars")
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
            if _controls.is_stop():
                return

        skip_phases, agents_cfg, video_enabled, email_enabled = reload_config()
        # ══════════════════════ PHASE 2: Deep Research ══════════════════════
        results = {}
        _user_skip_p2 = _controls.consume_phase_skip(2)
        if 2 in skip_phases or _user_skip_p2:
            _reason = "user_skip" if _user_skip_p2 else "Disabled in pipeline config"
            log(f"Phase 2: SKIPPED ({_reason})")
            emit_event("phase_skipped", phase=2, reason=_reason)
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
            # Active-time ceiling for Phase 2 — paused seconds don't count.
            # Per-phase login probe removed (2026-04-24) — Phase 0 is the
            # single login gate. See the matching note in the Phase 1
            # block above.
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
            # Restart loop: if mid-phase pause + input triggers a restart, merge
            # the new context into the brief and rerun the whole phase. Cap at
            # 3 restarts to prevent infinite loops if something goes sideways.
            results = {}
            _p2_user_skipped = False
            for _p2_attempt in range(3):
                _runtime.restart_requested = False
                while True:  # timeout-retry loop
                    try:
                        results = await _await_phase_with_active_deadline(
                            2, PHASE_2_MAX_MIN,
                            lambda: run_phase2(browser, cua_client, research_brief, verbose,
                                               enabled_agents=enabled_agents),
                        )
                        break  # success
                    except asyncio.TimeoutError:
                        _decision = await _phase_timeout_decision(2, PHASE_2_MAX_MIN)
                        if _decision == "retry":
                            emit_event("phase_restart", phase=2, reason="user_retry_after_timeout")
                            results = {}
                            continue
                        if _decision == "skip":
                            emit_event("phase_skipped", phase=2, reason="user_skip_after_timeout")
                            _p2_user_skipped = True
                            results = {}
                            break
                        emit_event("pipeline_stopped", phase=2, reason=f"user_{_decision}_after_timeout")
                        return
                if _p2_user_skipped:
                    break  # exit outer for loop too
                if not _runtime.restart_requested:
                    break
                extra_ctx_retry = _controls.pop_extra_context()
                if not extra_ctx_retry:
                    log("[Phase 2] restart_requested but extra_context empty — continuing", "WARN")
                    break
                research_brief += f'\n\nADDITIONAL USER CONTEXT (restart #{_p2_attempt+1}):\n{extra_ctx_retry}'
                log(f"[Phase 2] Mid-phase restart with +{len(extra_ctx_retry)} chars of user input")
                emit_event("phase_restart", phase=2,
                           reason="mid_phase_input_on_resume",
                           chars=len(extra_ctx_retry), attempt=_p2_attempt+1)
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
                # Compile source URLs from track events (DOM scraping)
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
            # ── 2026-04-25: Markdown-as-primary phase_complete (P1 mirror) ──
            # extract_and_record_agent already emitted link_extracted with the
            # in-app /documents primary the moment each agent's MD landed.
            # Share-link extraction is removed from P2; Phase 5's Doc creation
            # uses Phase 3's link extraction. So phase_complete just builds
            # _p2_links from the in-app primaries we already have.
            # Build _p2_links from per-agent in-app primaries — always present
            # when MD landed. Public share URLs (when the workers got them)
            # have already been emitted via link_extracted and the FE has
            # merged them into the agent's links list independently.
            _p2_links: list[dict] = []
            _p2_skipped_agents: list[str] = []
            for name, r in results.items():
                in_app = r.get("_in_app_url") or ""
                if in_app and r.get("text"):
                    _p2_links.append({
                        "label": f"Read {name} report",
                        "url": in_app,
                        "verified": True,
                        "primary": True,
                    })
                else:
                    _p2_skipped_agents.append(name)
            done_count = sum(1 for r in results.values() if r["status"] == "done")
            total_chars = sum(len(r.get("text", "")) for r in results.values())
            log(f"[Phase 2] Built {len(_p2_links)} in-app primary links, "
                f"{len(_p2_skipped_agents)} agents skipped (no MD)")
            # ── C8: phase_complete invariant — every non-skipped enabled agent ──
            # ── should have an in-app primary link entry. With the markdown-as- ──
            # ── primary architecture (2026-04-25), the in-app /documents URL is ──
            # ── always present when MD landed. Missing entries mean MD save     ──
            # ── itself failed for that agent — surface loudly so it's caught.   ──
            # Match by extracting the agent name from "Read {name} report" labels.
            _linked_agents = set()
            for _l in _p2_links:
                _lbl = _l.get("label") or ""
                # "Read ChatGPT report" → "ChatGPT"
                _parts = _lbl.split(" ")
                if len(_parts) >= 2 and _parts[0] == "Read":
                    _linked_agents.add(_parts[1])
            _expected_agents = set(results.keys()) - set(_p2_skipped_agents)
            _missing_links = _expected_agents - _linked_agents
            if _missing_links:
                log(f"[Phase 2] phase_complete invariant breach: {sorted(_missing_links)} "
                    f"are non-skipped but have no in-app primary link. Emitting "
                    f"phase_complete anyway — these agents will render as unlinked. "
                    f"Investigate why MD save / in-app URL build skipped them.", "ERROR")
            emit_event("phase_complete", phase=2, durationSec=int(time.time() - _p2_start), links=_p2_links,
                skippedAgents=_p2_skipped_agents,
                summary=f"{done_count}/{len(results)} agents completed — {total_chars:,} chars — "
                        f"{len(_p2_links)} in-app primary links")
            _update_firestore_research({"phase": 2, "links.phase2": _p2_links})
            # Phase-2 completion marker for resume safety. The marker tells
            # detect_resume_phase that Phase 2 actually finished — without
            # it, the previous "any non-brief MD >100 bytes → Phase 3" rule
            # would falsely jump to Phase 3 after a crash that killed 2/3
            # agents mid-research with only one MD on disk.
            #
            # CRITICAL: only write the marker on a CLEAN P2 finish — every
            # attempted agent reached a terminal state AND the user didn't
            # request stop/pause. Stop/pause flow through this same code
            # path (poll_all_agents_round_robin returns whatever it had),
            # and writing the marker there would silently drop unfinished
            # agents on resume. A legit "failed" status counts as terminal
            # (resume won't re-run an agent that already failed cleanly).
            _p2_clean_finish = (not _controls.is_stop_or_pause())
            if _p2_clean_finish:
                try:
                    (queue_dir / "phase2_complete.marker").write_text(
                        json.dumps({
                            "completedAt": int(time.time() * 1000),
                            "doneCount": done_count,
                            "totalAgents": len(results),
                            "skippedAgents": list(_p2_skipped_agents),
                        }),
                        encoding="utf-8",
                    )
                except Exception as _mk_e:
                    log(f"[Phase 2] failed to write phase2_complete.marker: {_mk_e}", "WARN")
            else:
                log("[Phase 2] stop/pause detected — skipping phase2_complete.marker so resume re-runs P2", "INFO")
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
                    results = await run_phase2(
                        browser, cua_client, combined_brief, verbose,
                        enabled_agents=enabled_agents_now)
                    # Rewrite documents
                    for name, r in results.items():
                        if r.get("text"):
                            fname = name.lower().replace(" ", "") + ".md"
                            _regen_md = f"# {name} Deep Research (regenerated)\n\n{r['text']}"
                            (queue_dir / "documents" / fname).write_text(_regen_md, encoding="utf-8")
                            save_document_to_firestore(name.lower().replace(" ", ""), _regen_md, f"{name} Deep Research")
                    # Build links from round-robin results — prefer in-app primary
                    # (always present when MD landed) over conversation URL.
                    _p2_links = []
                    for n, r in results.items():
                        in_app = r.get("_in_app_url") or ""
                        if in_app and r.get("text"):
                            _p2_links.append({"label": f"Read {n} report", "url": in_app,
                                              "verified": True, "primary": True})
                    emit_event("phase_complete", phase=2, links=_p2_links,
                               summary=f"Phase 2 regenerated with user input")

        # ── Check we have research output to continue ──
        # ARCHITECTURE 2026-04-18 (never-die): no retries_left cap. If
        # Phase 2 produced nothing, surface a phase alert and wait for
        # the user to choose Retry / Skip / Stop. Retry re-runs Phase 2;
        # Skip advances past Phase 3 entirely (no notebook/audio); Stop
        # ends the run. Previously we capped at 1 retry and then
        # silently marked the run failed — that broke the contract.
        doc_dir = queue_dir / "documents"
        md_files = [f for f in doc_dir.glob("*.md") if f.stat().st_size > 100 and f.stem != "brief"] if doc_dir.exists() else []
        has_results = md_files or any(r.get("text") for r in results.values())
        _p3gate_skipped = False
        _p3gate_attempt = 0
        while not has_results:
            _p3gate_attempt += 1
            log(f"No research output (attempt {_p3gate_attempt}) — awaiting user decision", "WARN")
            fail_phase(
                phase=3,
                error="Phase 2 produced no documents — can't continue to NotebookLM.",
                reason="All three agents timed out, errored, or returned empty. Retry re-runs Phase 2 with the same brief; Skip moves past Phase 3 (no notebook, no audio).",
                actions=[
                    {"id": "retry", "label": "Retry Phase 2", "style": "primary",
                     "command": {"action": "retry_phase", "phase": 3}},
                    {"id": "skip", "label": "Skip Phase 3", "style": "default",
                     "command": {"action": "skip_phase", "phase": 3}},
                ],
            )
            gate_decision = await _controls.await_phase_decision(3)
            log(f"Phase 3 gate decision: {gate_decision}")
            if gate_decision == "retry":
                try:
                    emit_event("phase_restart", phase=2, reason="user_retry_p3_gate", attempt=_p3gate_attempt + 1)
                except Exception:
                    pass
                _retry_brief_text = (brief_artifact.text if brief_artifact else brief_text) or ""
                _retry_enabled = [a for a, on in agents_cfg.items() if on]
                results = await run_phase2(
                    browser, cua_client, _retry_brief_text, verbose,
                    enabled_agents=_retry_enabled)
                # Rewrite documents from the fresh results
                for name, r in results.items():
                    if r.get("text"):
                        fname = name.lower().replace(" ", "") + ".md"
                        _regen_md = f"# {name} Deep Research (retry)\n\n{r['text']}"
                        (queue_dir / "documents" / fname).write_text(_regen_md, encoding="utf-8")
                        save_document_to_firestore(name.lower().replace(" ", ""), _regen_md, f"{name} Deep Research")
                # Re-check gate
                md_files = [f for f in doc_dir.glob("*.md") if f.stat().st_size > 100 and f.stem != "brief"] if doc_dir.exists() else []
                has_results = md_files or any(r.get("text") for r in results.values())
                continue
            if gate_decision == "skip":
                log("Phase 3 gate: user skipped — continuing past Phase 3 with no documents", "INFO")
                emit_event("phase_skipped", phase=3, reason="user_skip_no_docs")
                # await_phase_decision(3) already consumed the skip flag, so
                # re-add it to the set. The Phase 3 entry block below reads
                # consume_phase_skip(3) and will short-circuit past the upload
                # step when the flag is present.
                _controls.skipped_phases.add(3)
                _p3gate_skipped = True
                break
            # stop / timeout → end the run
            log(f"Phase 3 gate: user {gate_decision} — terminating pipeline", "INFO")
            emit_event("pipeline_stopped", phase=3, reason=f"user_{gate_decision}_no_docs")
            return

        # Post-Phase-2: add_context is no longer accepted (guarded at command
        # listener). Any residual extra_context from a pre-P2 race is dropped
        # with a warning — no NotebookLM addendum, no prompt, no cascade.
        if _controls.peek_extra_context():
            dropped = _controls.pop_extra_context()
            log(f"Dropping {len(dropped)} chars of residual extra_context post-P2 "
                f"(add_context disabled for Phase 3+)", "WARN")

        skip_phases, agents_cfg, video_enabled, email_enabled = reload_config()
        # ══════════════════════ PHASE 3: NotebookLM Processing (upload + audio) ══════════════════════
        audio_path = None
        _user_skip_p3 = _controls.consume_phase_skip(3)
        if 3 in skip_phases or _user_skip_p3:
            _reason = "user_skip" if _user_skip_p3 else "Disabled in pipeline config"
            log(f"Phase 3: SKIPPED ({_reason})")
            emit_event("phase_skipped", phase=3, reason=_reason)
        elif start_phase <= 3:
            emit_event("phase_start", phase=3, description="Uploading to NotebookLM + generating audio overview", agents=["notebooklm"])
            _update_firestore_research({"phase": 3, "currentPhase": 3, "status": "ongoing"})
            _p3_start = time.time()
            # Phase 3 has two sub-steps (upload, audio) with independent
            # active-time ceilings — see PHASE_3_UPLOAD_MAX_MIN and
            # PHASE_3_AUDIO_MAX_MIN. Paused seconds don't count.
            # Per-phase login probe removed (2026-04-24) — see Phase 1 note.
            if not results:
                for md_file in md_files:
                    stem = md_file.stem.lower()
                    name = {"chatgpt": "ChatGPT", "gemini": "Gemini", "claude": "Claude"}.get(stem, stem)
                    results[name] = {"status": "done", "text": md_file.read_text(encoding="utf-8"),
                                     "url": "", "page": None}
            # Sub-step 3a: Upload to NotebookLM
            _p3a_user_skipped = False
            while True:  # timeout-retry loop
                try:
                    p3 = await _await_phase_with_active_deadline(
                        3, PHASE_3_UPLOAD_MAX_MIN,
                        lambda: run_phase3_upload(browser, cua_client, results, topic, queue_dir, verbose),
                    )
                    break
                except asyncio.TimeoutError:
                    _decision = await _phase_timeout_decision(3, PHASE_3_UPLOAD_MAX_MIN, agent="notebooklm")
                    if _decision == "retry":
                        emit_event("phase_restart", phase=3, reason="user_retry_after_timeout")
                        continue
                    if _decision == "skip":
                        emit_event("phase_skipped", phase=3, reason="user_skip_after_timeout")
                        _p3a_user_skipped = True
                        p3 = {"links": {}, "notebook_url": ""}
                        break
                    emit_event("pipeline_stopped", phase=3, reason=f"user_{_decision}_after_timeout")
                    return
            links = p3.get("links", {})
            notebook_url = p3.get("notebook_url", "")
            # B1: Link-first — retry notebook URL extraction on validation failure.
            # ARCHITECTURE 2026-04-18 (never-die): wrap the retry in a decision
            # loop so repeated extract failures surface as a phase alert with
            # Retry / Skip instead of silently terminating.
            if not (notebook_url and validate_link("notebooklm", notebook_url)):
                log("[NotebookLM] Notebook URL missing/invalid — retrying via extractor (3×)", "WARN")
                while True:
                    nb_res = await extract_with_retry(
                        phase=3, agent="notebooklm", browser=browser, cua_client=cua_client,
                        extractor_fn=extract_notebooklm_url,
                        label="NotebookLM Notebook", verbose=verbose,
                    )
                    # 2026-04-25 (Commit 9 follow-up): `verified` now requires
                    # BOTH a NotebookLM URL shape AND a DOM-confirmed public
                    # share. The DOM-verify can fail for benign reasons
                    # (Material dropdown without aria-selected, transient
                    # eval error, dialog already closed), so gating the
                    # recovery loop on `verified` alone would starve fine
                    # notebooks. Accept URL-shape-only here — the link still
                    # works for the user even if not DOM-confirmed public.
                    # If the link turns out to be private, downstream Doc/email
                    # consumers will surface the auth error to the recipient,
                    # which is the only context where it actually matters.
                    if nb_res.verified or (nb_res.url and "notebooklm.google.com/notebook" in nb_res.url):
                        notebook_url = nb_res.url
                        if not nb_res.verified:
                            log("[NotebookLM] URL-shape OK but public-share NOT DOM-verified — "
                                "downstream link may be private", "WARN")
                        break
                    log(f"Phase 3: no verified NotebookLM URL after retries — awaiting user decision ({nb_res.error})", "ERROR")
                    fail_phase(
                        phase=3,
                        error=f"Could not extract verified NotebookLM URL: {nb_res.error}",
                        reason="NotebookLM extraction couldn't confirm a valid notebook URL. Retry tries again; Skip moves past Phase 3 without a notebook link.",
                        agent="notebooklm",
                    )
                    decision = await _controls.await_phase_decision(3)
                    if decision == "retry":
                        log("Phase 3 link extraction: user requested retry", "INFO")
                        emit_event("phase_restart", phase=3, reason="user_retry_link_extract", attempt=0)
                        continue
                    if decision == "skip":
                        log("Phase 3 link extraction: user skipped — proceeding without notebook URL", "INFO")
                        notebook_url = ""
                        break
                    log(f"Phase 3 link extraction: user {decision} — terminating pipeline", "INFO")
                    emit_event("pipeline_stopped", phase=3, reason=f"user_{decision}_link_extract")
                    return
            else:
                emit_validated_link(3, "notebooklm", notebook_url, "NotebookLM Notebook")
            (queue_dir / "links.json").write_text(json.dumps(links, indent=2), encoding="utf-8")
            save_checkpoint(queue_dir, 3, topic=topic, brief_url=brief_url,
                            notebook_url=notebook_url)
            update_delivery(research_links=links, notebook_url=notebook_url)
            # Sub-step 3b: Generate audio overview
            audio_overview_url = ""
            if notebook_url:
                while True:  # timeout-retry loop
                    try:
                        p4 = await _await_phase_with_active_deadline(
                            3, PHASE_3_AUDIO_MAX_MIN,
                            lambda: run_phase3_audio(browser, cua_client, notebook_url, queue_dir, verbose),
                        )
                        break
                    except asyncio.TimeoutError:
                        _decision = await _phase_timeout_decision(3, PHASE_3_AUDIO_MAX_MIN, agent="notebooklm")
                        if _decision == "retry":
                            emit_event("phase_restart", phase=3, reason="user_retry_audio_timeout")
                            continue
                        if _decision == "skip":
                            emit_event("phase_skipped", phase=3, reason="user_skip_audio_timeout")
                            p4 = {"audio_path": None, "audio_overview_url": ""}
                            break
                        emit_event("pipeline_stopped", phase=3, reason=f"user_{_decision}_audio_timeout")
                        return
                audio_path = p4.get("audio_path")
                audio_overview_url = p4.get("audio_overview_url", "")
                save_checkpoint(queue_dir, 3, topic=topic, brief_url=brief_url,
                                notebook_url=notebook_url,
                                audio_path=str(audio_path) if audio_path else "",
                                audio_overview_url=audio_overview_url)
                # Use audio overview URL if available, else notebook URL for audio reference
                _audio_link = audio_overview_url or notebook_url
                update_delivery(audio_url=_audio_link)
                if audio_overview_url:
                    emit_validated_link(3, "notebooklm", audio_overview_url, "Audio Overview")
            save_meta(queue_dir, topic, 3)
            # Build Phase 3 links — include both notebook and audio overview
            # Only include links that pass validation (no fake/placeholder URLs)
            _p3_links = []
            if notebook_url and validate_link("notebooklm", notebook_url):
                _p3_links.append({"label": "NotebookLM Notebook", "url": notebook_url, "verified": True})
            if audio_overview_url and audio_overview_url != notebook_url and validate_link("notebooklm", audio_overview_url):
                _p3_links.append({"label": "Audio Overview", "url": audio_overview_url, "verified": True})
            emit_event("phase_complete", phase=3, durationSec=int(time.time() - _p3_start), links=_p3_links,
                summary=f"NotebookLM notebook created{', audio generated' if audio_path else ''}{', audio link extracted' if audio_overview_url else ''}")
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
                # Post-P2 input is disabled. Drop any residual buffer silently.
                if _controls.peek_extra_context():
                    _ = _controls.pop_extra_context()

        skip_phases, agents_cfg, video_enabled, email_enabled = reload_config()
        # ══════════════════════ PHASE 4: YouTube Upload ══════════════════════
        _user_skip_p4 = _controls.consume_phase_skip(4)
        if 4 in skip_phases or not video_enabled or _user_skip_p4:
            _reason = "user_skip" if _user_skip_p4 else ("Disabled in pipeline config" if 4 in skip_phases else "Video disabled")
            log(f"Phase 4: SKIPPED ({_reason})")
            emit_event("phase_skipped", phase=4, reason=_reason)
        elif start_phase <= 4:
            emit_event("phase_start", phase=4, description="Converting audio to video + YouTube upload", agents=["youtube"])
            _update_firestore_research({"phase": 4, "currentPhase": 4, "status": "ongoing"})
            _p4_start = time.time()
            # Active-time ceiling — paused seconds don't count.
            # Per-phase login probe removed (2026-04-24) — see Phase 1 note.
            if audio_path:
                _p4_user_skipped = False
                while True:  # timeout-retry loop
                    try:
                        p5 = await _await_phase_with_active_deadline(
                            4, PHASE_4_MAX_MIN,
                            lambda: run_phase4(browser, cua_client, audio_path, topic, queue_dir,
                                               links=links, notebook_url=notebook_url, verbose=verbose),
                        )
                        break
                    except asyncio.TimeoutError:
                        # Phase 4 retry has an idempotency note: re-running ffmpeg
                        # is fine, but YouTube upload is NOT idempotent —
                        # retry-after-partial may produce a duplicate video.
                        # Document via fail_phase reason; user accepts the risk.
                        _decision = await _phase_timeout_decision(4, PHASE_4_MAX_MIN, agent="youtube")
                        if _decision == "retry":
                            emit_event("phase_restart", phase=4, reason="user_retry_after_timeout")
                            continue
                        if _decision == "skip":
                            emit_event("phase_skipped", phase=4, reason="user_skip_after_timeout")
                            _p4_user_skipped = True
                            p5 = {"youtube_url": ""}
                            break
                        emit_event("pipeline_stopped", phase=4, reason=f"user_{_decision}_after_timeout")
                        return
                youtube_url = p5.get("youtube_url", "")
                # B1: Link-first — retry YouTube URL extraction on validation failure.
                # ARCHITECTURE 2026-04-18 (never-die): wrap the retry in a
                # decision loop so repeated extract failures surface as a
                # phase alert with Retry / Skip instead of silently
                # terminating.
                if not (youtube_url and validate_link("youtube", youtube_url)):
                    if youtube_url:
                        log(f"[YouTube] REJECTED invalid URL: {youtube_url} — retrying extractor (3×)", "WARN")
                    else:
                        log("[YouTube] No URL from upload — retrying extractor (3×)", "WARN")
                    while True:
                        yt_res = await extract_with_retry(
                            phase=4, agent="youtube", browser=browser, cua_client=cua_client,
                            extractor_fn=extract_youtube_url,
                            label="YouTube Video", verbose=verbose,
                        )
                        if yt_res.verified:
                            youtube_url = yt_res.url
                            break
                        log(f"Phase 4: no verified YouTube URL after retries — awaiting user decision ({yt_res.error})", "ERROR")
                        fail_phase(
                            phase=4,
                            error=f"Could not extract verified YouTube URL: {yt_res.error}",
                            reason="YouTube extraction couldn't confirm a valid video URL. Retry tries again; Skip moves past Phase 4 without a video link.",
                            agent="youtube",
                        )
                        decision = await _controls.await_phase_decision(4)
                        if decision == "retry":
                            log("Phase 4 link extraction: user requested retry", "INFO")
                            emit_event("phase_restart", phase=4, reason="user_retry_link_extract", attempt=0)
                            continue
                        if decision == "skip":
                            log("Phase 4 link extraction: user skipped — proceeding without YouTube URL", "INFO")
                            youtube_url = ""
                            break
                        log(f"Phase 4 link extraction: user {decision} — terminating pipeline", "INFO")
                        emit_event("pipeline_stopped", phase=4, reason=f"user_{decision}_link_extract")
                        return
                else:
                    emit_validated_link(4, "youtube", youtube_url, "YouTube Video")
                save_checkpoint(queue_dir, 4, topic=topic, brief_url=brief_url,
                                notebook_url=notebook_url, youtube_url=youtube_url)
                update_delivery(youtube_url=youtube_url)
                save_meta(queue_dir, topic, 4)
                _p4_links = [{"label": "YouTube Video", "url": youtube_url, "verified": True}]
                emit_event("phase_complete", phase=4, durationSec=int(time.time() - _p4_start), links=_p4_links,
                    summary=f"Video uploaded: {youtube_url}")
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
        _user_skip_p5 = _controls.consume_phase_skip(5)
        if 5 in skip_phases or not email_enabled or _user_skip_p5:
            _reason = "user_skip" if _user_skip_p5 else ("Disabled in pipeline config" if 5 in skip_phases else "Email disabled")
            log(f"Phase 5: SKIPPED ({_reason})")
            emit_event("phase_skipped", phase=5, reason=_reason)
        else:
            emit_event("phase_start", phase=5, description="Creating Google Doc hub + sending email notification", agents=["gdocs", "gmail"])
            _update_firestore_research({"phase": 5, "currentPhase": 5, "status": "ongoing"})
            _p5_start = time.time()
            # Active-time ceiling — paused seconds don't count.
            # Per-phase login probe removed (2026-04-24) — see Phase 1 note.
            # Use audio overview URL if extracted, else notebook URL as fallback
            _effective_audio_url = audio_overview_url if audio_overview_url else notebook_url
            _p5_user_skipped = False
            while True:  # timeout-retry loop
                try:
                    p6 = await _await_phase_with_active_deadline(
                        5, PHASE_5_MAX_MIN,
                        lambda: run_phase5(browser, cua_client, topic, links, notebook_url, youtube_url,
                                           brief_url=brief_url, audio_url=_effective_audio_url,
                                           email=email, verbose=verbose),
                    )
                    break
                except asyncio.TimeoutError:
                    # Phase 5 retry caveat: GDoc creation is idempotent (creates
                    # a fresh doc), but Gmail send is NOT — retry may send a
                    # duplicate email if prior attempt got that far.
                    _decision = await _phase_timeout_decision(5, PHASE_5_MAX_MIN)
                    if _decision == "retry":
                        emit_event("phase_restart", phase=5, reason="user_retry_after_timeout")
                        continue
                    if _decision == "skip":
                        emit_event("phase_skipped", phase=5, reason="user_skip_after_timeout")
                        _p5_user_skipped = True
                        p6 = {"doc_url": ""}
                        break
                    emit_event("pipeline_stopped", phase=5, reason=f"user_{_decision}_after_timeout")
                    return
            doc_url = p6.get("doc_url", "")
            # B1: Link-first — retry Google Doc URL extraction on validation failure.
            # ARCHITECTURE 2026-04-18 (never-die): wrap retries in a
            # decision loop so the user sees Retry / Skip instead of a
            # silent termination.
            if not (doc_url and validate_link("gdocs", doc_url)):
                if doc_url:
                    log(f"[Google Doc] URL doesn't look right: {doc_url} — retrying extractor (3×)", "WARN")
                else:
                    log("[Google Doc] No URL returned — retrying extractor (3×)", "WARN")
                while True:
                    gd_res = await extract_with_retry(
                        phase=5, agent="gdocs", browser=browser, cua_client=cua_client,
                        extractor_fn=extract_gdoc_url,
                        label="Google Doc Hub", verbose=verbose,
                    )
                    if gd_res.verified:
                        doc_url = gd_res.url
                        break
                    log(f"Phase 5: no verified Google Doc URL after retries — awaiting user decision ({gd_res.error})", "ERROR")
                    fail_phase(
                        phase=5,
                        error=f"Could not extract verified Google Doc URL: {gd_res.error}",
                        reason="Google Doc extraction couldn't confirm a valid URL. Retry tries again; Skip moves past Phase 5 without a report link (email/notification step may be skipped too).",
                        agent="gdocs",
                    )
                    decision = await _controls.await_phase_decision(5)
                    if decision == "retry":
                        log("Phase 5 link extraction: user requested retry", "INFO")
                        emit_event("phase_restart", phase=5, reason="user_retry_link_extract", attempt=0)
                        continue
                    if decision == "skip":
                        log("Phase 5 link extraction: user skipped — proceeding without Google Doc URL", "INFO")
                        doc_url = ""
                        break
                    log(f"Phase 5 link extraction: user {decision} — terminating pipeline", "INFO")
                    emit_event("pipeline_stopped", phase=5, reason=f"user_{decision}_link_extract")
                    return
            else:
                emit_validated_link(5, "gdocs", doc_url, "Google Doc Hub")
            update_delivery(doc_url=doc_url, email_sent=p6.get("email_sent", False),
                            status="completed")
            save_checkpoint(queue_dir, 5, topic=topic, brief_url=brief_url, notebook_url=notebook_url,
                            youtube_url=youtube_url, doc_url=doc_url)
            save_meta(queue_dir, topic, 5, status="completed")
            _p5_links = [{"label": "Google Doc Hub", "url": doc_url, "verified": True}]
            if p6.get("email_sent"):
                _p5_links.append({"label": "Open Gmail", "url": "https://mail.google.com", "verified": True})
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
        # Uncaught exception anywhere in the pipeline — surface it with
        # whatever phase context we have so the frontend can route the
        # error to the correct phase tile instead of silently dropping it.
        import traceback
        tb = traceback.format_exc()
        log(f"Fatal: {e}", "ERROR")
        traceback.print_exc()
        # _runtime.phase is the most-recently-entered phase — use it as
        # the routing hint so the error lands on the right phase tile
        # instead of defaulting to 0 and polluting the P0 dropdown.
        last_phase = 0
        try:
            rp = getattr(_runtime, "phase", None)
            if isinstance(rp, int):
                last_phase = rp
        except Exception:
            pass
        fail_phase(
            phase=last_phase,
            error=str(e)[:200] or "unexpected failure",
            reason="The pipeline hit an unexpected error. Details saved to backend.log and tracks/events.jsonl.",
            agent=None,
        )
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

    # ── Startup sweep: purge stale failed runs older than 7 days ──
    # Without this, queues/ and tracks/ pile up forever with partial MDs,
    # partial audio, and orphaned Firestore docs. We only sweep entries whose
    # delivery.json status is NOT in a clean-parked set, and only if the dir
    # hasn't been touched in > 7 days so active debugging sessions aren't
    # wiped out.
    try:
        now_ts = time.time()
        STALE_SECONDS = 7 * 86400
        KEEP_STATUSES = {"completed", "paused", "paused_backend_restart"}
        swept = 0
        if queues_root.exists():
            for d in queues_root.iterdir():
                if not d.is_dir():
                    continue
                delivery_path = d / "delivery.json"
                status = ""
                try:
                    if delivery_path.exists():
                        status = json.loads(delivery_path.read_text(encoding="utf-8")).get("status", "")
                except Exception:
                    pass
                if status in KEEP_STATUSES:
                    continue
                try:
                    mtime = d.stat().st_mtime
                except Exception:
                    continue
                if (now_ts - mtime) < STALE_SECONDS:
                    continue
                # Cascade Firestore cleanup if owner.json is present
                owner_path = d / "owner.json"
                if owner_path.exists() and _firebase_db:
                    try:
                        owner = json.loads(owner_path.read_text(encoding="utf-8"))
                        uid, rid = owner.get("uid"), owner.get("researchId")
                        if uid and rid:
                            ref = _firebase_db.collection("users").document(uid) \
                                .collection("researches").document(rid)
                            for sub in ("documents", "audios", "messages",
                                        "pipeline_events", "commands"):
                                try:
                                    for sd in ref.collection(sub).stream():
                                        try: sd.reference.delete()
                                        except Exception: pass
                                except Exception: pass
                            try: ref.delete()
                            except Exception: pass
                    except Exception: pass
                # Nuke local dirs
                import shutil as _shutil
                try: _shutil.rmtree(d)
                except Exception: pass
                try:
                    tdir = tracks_root / d.name
                    if tdir.exists(): _shutil.rmtree(tdir)
                except Exception: pass
                swept += 1
        if swept:
            log(f"[startup-sweep] purged {swept} stale run(s) older than 7 days", "INFO")
    except Exception as _se:
        log(f"[startup-sweep] failed: {_se}", "WARN")

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
        """STOP: terminate pipeline, save partial results, mark as stopped (not resumable).

        Also schedules a hard process exit 3s later — matches the Firestore
        command-listener path so that hitting Stop reliably ends the backend
        no matter which transport got there first.
        """
        queue = queues_root / run_id
        if not queue.exists():
            return JSONResponse({"error": "not found"}, 404)
        (queue / ".stop").write_text("stop", encoding="utf-8")
        p = queue / ".pause"
        if p.exists():
            p.unlink()
        # Set asyncio event for immediate response, then schedule the backend
        # exit via the shared helper. Idempotent if the Firestore-command path
        # already fired — we won't spawn duplicate exit threads.
        _controls.request_stop()
        _schedule_server_exit("http-endpoint")
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
        Only valid during Phase 1; Phase 2+ rejects (matches FE input lock + Firestore listener).
        Body: {text: "Also look at biotech angle"}"""
        queue = queues_root / run_id
        if not queue.exists():
            return JSONResponse({"error": "not found"}, 404)
        text = request_data.get("text", "")
        if not text:
            return JSONResponse({"error": "text is required"}, 400)
        if _runtime.phase >= 2:
            log(f"REST add_context REJECTED (phase={_runtime.phase} — input disabled from Phase 2 onward)", "WARN")
            return JSONResponse({"error": f"context rejected — phase {_runtime.phase} does not accept input"}, 409)
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
    _QUEUE_STATE["queue_ref"] = _job_queue
    _QUEUE_STATE["recompute_fn"] = None  # set below after defining helper

    def _flip_queued_to_ongoing(uid_val, research_id_val):
        """Worker pickup: flip status from queued → ongoing and clear queue
        fields. No-op if Firestore is unavailable or uid/rid missing (HTTP
        /api/runs path doesn't carry them)."""
        if not (_firebase_db and uid_val and research_id_val):
            return
        try:
            from google.cloud.firestore import DELETE_FIELD
            _firebase_db.collection("users").document(uid_val) \
                .collection("researches").document(research_id_val) \
                .update({
                    "status": "ongoing",
                    "queuePosition": DELETE_FIELD,
                    "queuedBehindRunId": DELETE_FIELD,
                    "queuedBehindTitle": DELETE_FIELD,
                })
        except Exception as e:
            log(f"Failed to flip queued→ongoing for {research_id_val}: {e}", "WARN")

    def _recompute_queue_positions():
        """After a job finishes, shift remaining queued jobs' positions up by
        one and re-point their `queuedBehindRunId/Title` at the new head (or
        clear if they're next). Reads `_job_queue._queue` as a snapshot."""
        if not _firebase_db:
            return
        try:
            pending = list(_job_queue._queue)
        except Exception:
            return
        for idx, qjob in enumerate(pending):
            uid_v = qjob.get("uid")
            rid_v = qjob.get("research_id")
            if not uid_v or not rid_v:
                continue
            new_pos = idx + 1
            # The head job (idx 0) waits behind nothing — it starts next.
            # Others wait behind the job immediately before them.
            if idx == 0:
                patch = {"queuePosition": new_pos}
                try:
                    from google.cloud.firestore import DELETE_FIELD
                    patch["queuedBehindRunId"] = DELETE_FIELD
                    patch["queuedBehindTitle"] = DELETE_FIELD
                except Exception:
                    pass
            else:
                prev = pending[idx - 1]
                patch = {
                    "queuePosition": new_pos,
                    "queuedBehindRunId": prev.get("research_id") or "",
                    "queuedBehindTitle": (prev.get("topic") or "")[:60],
                }
            try:
                _firebase_db.collection("users").document(uid_v) \
                    .collection("researches").document(rid_v) \
                    .update(patch)
            except Exception as e:
                log(f"Failed to recompute queue position for {rid_v}: {e}", "WARN")

    # Expose the recompute helper to the module-level Firestore listener so
    # the cancel-queued action can also trigger a position refresh.
    _QUEUE_STATE["recompute_fn"] = _recompute_queue_positions

    async def _job_worker():
        """Process pipeline jobs one at a time from the queue."""
        nonlocal _queue_running
        while True:
            job = await _job_queue.get()
            _queue_running = True
            _QUEUE_STATE["running"] = True
            _QUEUE_STATE["current_job"] = job
            log(f"Starting queued job: {job['topic'][:60]}")
            # Flip this run's research doc from queued → ongoing. No-op for
            # the very first start in an idle backend (already ongoing).
            _flip_queued_to_ongoing(job.get("uid"), job.get("research_id"))
            try:
                await run_pipeline(topic=job["topic"], email=job.get("email", ""),
                                   verbose=True, resume_dir=job.get("resume_dir"),
                                   config=job.get("config"), run_id=job.get("run_id"),
                                   uid=job.get("uid"), research_id=job.get("research_id"),
                                   brief_text=job.get("brief_text", ""))
            except Exception as e:
                log(f"Pipeline job error: {e}", "ERROR")
            finally:
                _queue_running = False
                _QUEUE_STATE["running"] = False
                _QUEUE_STATE["current_job"] = None
                _job_queue.task_done()
                # Shift remaining queued jobs up one position.
                _recompute_queue_positions()

    # Worker + Firestore start listener are launched below in the direct
    # startup path (before `await server.serve()`). We used to ALSO register
    # an `@app.on_event("startup")` handler that did the same thing as a
    # belt-and-suspenders fallback — but FastAPI did fire it, and the result
    # was TWO concurrent `_job_worker` tasks. Queue #2 got popped by worker
    # B while worker A was still running #1, a second Browser(PROFILE_DIR)
    # was instantiated, and Browser.start()'s orphan-Chrome sweep killed
    # #1's browser mid-flight. Single-worker startup is now the only path.

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
        """Delete a completed/stopped run's queue, tracks, and cascade-delete
        the matching Firestore documents/audios/messages/pipeline_events/
        commands subcollections. Without the cascade, partial docs from failed
        runs would linger in Firestore forever."""
        import shutil
        queue = queues_root / run_id
        tracks = tracks_root / run_id
        if not queue.exists() and not tracks.exists():
            return JSONResponse({"error": "not found"}, 404)

        # ── Cascade Firestore cleanup before nuking the owner file ──
        owner_path = queue / "owner.json"
        if owner_path.exists() and _firebase_db:
            try:
                owner = json.loads(owner_path.read_text(encoding="utf-8"))
                uid = owner.get("uid")
                rid = owner.get("researchId")
                if uid and rid:
                    research_ref = _firebase_db.collection("users").document(uid) \
                        .collection("researches").document(rid)
                    # Delete known subcollections. Firestore requires enumerating
                    # docs and deleting individually — no native recursive delete
                    # in the Python SDK's positional-arg API.
                    for sub in ("documents", "audios", "messages",
                                "pipeline_events", "commands"):
                        try:
                            for sd in research_ref.collection(sub).stream():
                                try: sd.reference.delete()
                                except Exception: pass
                        except Exception as _se:
                            log(f"[delete_run] subcollection {sub} sweep: {_se}", "WARN")
                    # Finally drop the research doc itself
                    try: research_ref.delete()
                    except Exception as _rde:
                        log(f"[delete_run] research doc delete: {_rde}", "WARN")
                    log(f"[delete_run] cascaded Firestore for users/{uid}/researches/{rid}")
            except Exception as _oe:
                log(f"[delete_run] owner.json parse failed: {_oe}", "WARN")

        try:
            if queue.exists(): shutil.rmtree(queue)
            if tracks.exists(): shutil.rmtree(tracks)
        except Exception as e:
            return JSONResponse({"error": str(e)}, 500)
        return {"status": "deleted", "id": run_id}

    @app.post("/api/runs")
    async def start_run(request_data: dict):
        """Start a new pipeline run. Queued if another is already running.
        Body: {topic, email?, briefText?, config?: {agents, skipPhases, videoEnabled, emailEnabled}}

        briefText: inline brief content that bypasses Phase 1 brief generation.
        When provided, Phase 1 is skipped and Phase 2 runs against this brief."""
        topic = request_data.get("topic")
        if not topic or not topic.strip():
            return JSONResponse({"error": "topic is required"}, 400)
        topic = topic.strip()
        email = request_data.get("email", "")
        uid = request_data.get("uid", "")  # Firebase user ID for Firestore bridge
        config = request_data.get("config", {})
        brief_text = (request_data.get("briefText") or "").strip()
        # Validate config
        agents_cfg = config.get("agents", {"chatgpt": True, "gemini": True, "claude": True})
        if not any(agents_cfg.values()):
            return JSONResponse({"error": "at least one agent must be enabled"}, 400)
        from datetime import datetime as _dt
        run_id = f"{safe_name(topic)}_{_dt.now().strftime('%Y%m%d_%H%M%S')}"
        await _job_queue.put({"topic": topic, "email": email, "config": config,
                              "run_id": run_id, "uid": uid, "brief_text": brief_text})
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
    # Load ResearchToken (required for token-scoped queue + heartbeat)
    token = load_research_token()
    if token:
        log(f"ResearchToken loaded: {token[:8]}...")
    else:
        log("No ResearchToken found — run `python research.py --pair` to generate one", "WARN")
        log("Falling back to legacy pipeline_requests/ listener", "WARN")
    worker_task = asyncio.create_task(_job_worker())
    log("Job worker started (direct)")
    # Firestore start listener — must fire exactly once per serve session.
    # This used to live inside an @app.on_event("startup") handler alongside
    # a second _job_worker create_task; that duplicated the worker and caused
    # the queue race where #2 killed #1's browser mid-run. Single-start here.
    if _firebase_db:
        start_firestore_start_listener(_job_queue, asyncio.get_event_loop())
    # Start heartbeat so frontend can show Online/Offline status
    heartbeat_task = None
    if token and _firebase_db:
        heartbeat_task = asyncio.create_task(_heartbeat_loop())
        log(f"Heartbeat started ({HEARTBEAT_INTERVAL_SEC}s interval)")
        # Refresh the paired device doc so the Account page sees this PC
        # online immediately on server start. If pairedUid isn't pinned yet
        # (pre-multi-device config), resolve it from the token's linkedUid.
        paired_uid = load_paired_uid()
        if not paired_uid:
            try:
                snap = _firebase_db.collection("research_tokens").document(token).get()
                if snap.exists:
                    paired_uid = (snap.to_dict() or {}).get("linkedUid") or ""
                    if paired_uid:
                        save_device_config(paired_uid=paired_uid)
            except Exception as e:
                log(f"Could not resolve paired uid from token doc: {e}", "WARN")
        if paired_uid:
            write_device_doc(paired_uid, token)
            # Queue rehydration: recover runs that were queued or mid-run when
            # the previous daemon process died. Queued jobs re-enter the in-
            # memory queue; mid-run jobs can't safely resume (browser/CUA state
            # is gone) so they're marked stopped with a clear reason. Without
            # this, the frontend shows "queued" forever after a backend crash.
            try:
                rehydrated = 0
                orphaned = 0
                researches_col = _firebase_db.collection("users").document(paired_uid) \
                    .collection("researches")
                for status_val in ("queued", "ongoing"):
                    try:
                        snaps = list(researches_col.where("status", "==", status_val).get())
                    except Exception as e:
                        log(f"Rehydrate query ({status_val}) failed: {e}", "WARN")
                        continue
                    for snap in snaps:
                        data = snap.to_dict() or {}
                        research_id = snap.id
                        if status_val == "ongoing":
                            # Mark as paused_backend_restart so the frontend can
                            # render a dedicated "Resume from checkpoint" CTA.
                            # Browser + CUA state is gone, but checkpoints on
                            # disk (documents/, tracks/, delivery.json) let the
                            # orchestrator skip already-completed phases via
                            # detect_resume_phase() and pick up from there.
                            try:
                                researches_col.document(research_id).update({
                                    "status": "paused_backend_restart",
                                    "summary": "Backend restarted mid-run — hit Resume to pick up from the last checkpoint.",
                                })
                                orphaned += 1
                            except Exception as e:
                                log(f"Rehydrate: mark paused_backend_restart failed for {research_id}: {e}", "WARN")
                        else:  # queued
                            topic = data.get("topic", "")
                            if not topic:
                                continue
                            # Research doc uses pipelineConfig.skippedPhases; backend
                            # run_pipeline reads skipPhases. Translate on rehydrate.
                            cfg = dict(data.get("pipelineConfig") or {})
                            if "skippedPhases" in cfg and "skipPhases" not in cfg:
                                cfg["skipPhases"] = cfg.pop("skippedPhases")
                            _job_queue.put_nowait({
                                "topic": topic,
                                "email": "",  # not persisted on research doc; Phase 5 email will skip
                                "config": cfg,
                                "run_id": data.get("backendRunId") or "",
                                "uid": paired_uid,
                                "research_id": research_id,
                            })
                            rehydrated += 1
                if rehydrated or orphaned:
                    log(f"Queue rehydration: re-enqueued {rehydrated} queued, marked {orphaned} orphaned runs stopped")
            except Exception as e:
                log(f"Queue rehydration failed: {e}", "WARN")
        # Sub-second relink: watch the token doc so a paste-token flow
        # (which only writes linkedUid, never touches the device doc) gets
        # reflected in the Account page tile almost immediately, instead of
        # waiting up to 30s for the heartbeat-based self-heal.
        _start_token_relink_watcher(token)

    # ── Branded --serve banner — 'aegis, standing watch' ──
    # Shows which account this backend is paired to, where it's listening,
    # and how to tear it down. Keeps the structural DNA of --pair /
    # --resurrect / --retire (SUPER RESEARCH wordmark + dim rule + Latin
    # tagline) so the three commands feel like a matched set.
    _branded_header("aegis", _BOLD + _ACCENT, "standing watch")
    _paired_uid_now = load_paired_uid()
    _paired_email = _fetch_paired_email(_paired_uid_now)
    token_short = f"{_research_token[:8]}…" if _research_token else "(none)"
    token_val = (f"{_c(_BOLD, token_short)}  {_c(_OK, '(active)')}"
                 if _research_token else _c(_DIM, "(none)"))
    _render_context_strip([
        ("Paired to", _c(_BOLD, _paired_email or "(not paired)")),
        ("Token",     token_val),
        ("Local API", _c(_BOLD, f"http://0.0.0.0:{port}")),
        ("Heartbeat", _c(_BOLD, f"{HEARTBEAT_INTERVAL_SEC}s cadence")),
    ])
    print()
    print(f"  {_c(_BOLD + _ACCENT, '  Listening for pipeline jobs.')}  {_c(_DIM, 'Keep this terminal open.')}")
    print()
    print(f"  {_c(_DIM, 'Stop:')}  {_c(_BOLD, 'Ctrl+C')}")

    # Context-aware hint: fresh users running --serve without pairing see
    # the banner succeed (port bound, listeners started) but no jobs will
    # ever arrive until the app claims a token. Surface --pair. If paired
    # but On Startup isn't enabled, surface --resurrect so users discover
    # the "run in background" capability.
    _currently_supervised = _detect_supervised()
    if not (_research_token and _paired_uid_now):
        print()
        print(f"  {_c(_WARN, '⚠')}  Not paired yet — jobs will be ignored until this machine is paired.")
        _render_next_actions([
            ("python research.py --pair", "pair this machine to your account"),
        ])
    elif not _currently_supervised:
        _render_next_actions([
            ("python research.py --resurrect", "enable On Startup (auto-start in background)"),
            ("python research.py --unpair",    "fully disconnect this machine"),
        ])
    else:
        _render_next_actions([
            ("python research.py --retire", "disable On Startup"),
            ("python research.py --unpair", "fully disconnect this machine"),
        ])

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        worker_task.cancel()
        if heartbeat_task:
            heartbeat_task.cancel()
        global _token_relink_watch
        if _token_relink_watch is not None:
            try:
                _token_relink_watch.unsubscribe()
            except Exception:
                pass
            _token_relink_watch = None
        # Mark the token offline on shutdown as a hint — the authoritative
        # online/offline signal is heartbeat age on the device doc, which
        # ages past the 60s threshold naturally when the serve stops. We do
        # NOT stamp a stale heartbeat on the device doc here: under
        # daemon-loop supervision this finally block fires on every respawn
        # cycle (e.g. port-bind crashloop), and the oscillation between
        # fresh-heartbeat-on-start and stale-on-finally causes green↔red
        # flicker in the UI.
        if _firebase_db and _research_token:
            try:
                _firebase_db.collection("research_tokens").document(_research_token).update({"status": "offline"})
            except Exception:
                pass


# ── Setup ────────────────────────────────────────────────────────────────────

async def run_pair(profile_dir, wait_minutes=10):
    """Guided setup: generate/reuse ResearchToken, render ASCII QR, open
    login tabs, auto-verify per-platform login every 30s, exit cleanly when
    all green (or on user Ctrl+C / timeout).

    Markers only tick after a real authenticated signal in the DOM — generic
    chat-input elements are deliberately excluded from LOGIN_PLATFORMS.

    QR payload is the bare token string so the in-app scanner just extracts
    + saves to the user's Firebase profile — no URL round-trips needed.
    """
    _setup_logo()

    # ══════════════════════════════════════════════════════════════════════
    # [1/4] TOKEN SETUP — mint, register in Firestore, render QR, wait for
    #       the app to claim the link. All token-side work lives here.
    # ══════════════════════════════════════════════════════════════════════
    _setup_step(1, 4, "Token setup")

    firebase_ok = init_firebase()
    if not firebase_ok:
        log("    Firebase unavailable — the app will NOT be able to validate this token.", "ERROR")
        log("    Check firebase-service-account.json and your network. Exiting.", "ERROR")
        return

    # ── Device display name ────────────────────────────────────────────────
    # Auto-named from the OS hostname (e.g. "SYAM-PC") and written to
    # users/{uid}/devices/{deviceId}.name at the end of setup. The user
    # renames it from the Account page if they want something else, so
    # prompting for it in the terminal is redundant friction.
    import socket as _socket
    chosen_device_name = _socket.gethostname()

    existing = load_research_token()
    # Track whether we minted the token this run. If the user Ctrl+Cs or
    # the wait loop times out below, we tear down a freshly-minted Firestore
    # token doc so aborted setups leave no orphan behind. Reused tokens
    # (from a prior successful --pair's local config) are preserved — the
    # user is likely just retrying.
    new_token_minted = False
    if existing:
        token = existing
        print(f"  {_c(_DIM, 'Reusing existing token')}  {_c(_DIM, '·')}  delete {RESEARCH_CONFIG_PATH.name} for a fresh one.")
    else:
        token = generate_research_token()
        new_token_minted = True
        print(f"  {_c(_OK, 'Minted new token.')}")

    # Upsert in Firestore on every --pair run so a reused local token can't
    # drift out of sync with what the app reads.
    try:
        import socket
        from google.cloud.firestore import SERVER_TIMESTAMP
        _firebase_db.collection("research_tokens").document(token).set({
            "status": "active",
            "machineName": socket.gethostname(),
            "lastHeartbeat": SERVER_TIMESTAMP,
            "createdAt": SERVER_TIMESTAMP,
        }, merge=True)
        print(f"  {_c(_OK, '✓')} Registered with {_c(_BOLD, _firebase_db.project)}")
    except Exception as e:
        log("    FIRESTORE REGISTRATION FAILED — the app will reject this token.", "ERROR")
        log(f"        {e}", "ERROR")
        return

    print()
    print(f"  {_c(_DIM, 'Token')}")
    print(f"  {_c(_BOLD + _ACCENT, token)}")
    print()
    try:
        import qrcode
        qr = qrcode.QRCode(border=1, box_size=1,
                           error_correction=qrcode.constants.ERROR_CORRECT_L)
        qr.add_data(token)
        qr.make(fit=True)
        qr.print_ascii(tty=True, invert=True)
    except ImportError:
        log("    qrcode lib missing — run `pip install -r requirements.txt` first.", "WARN")
    except Exception as e:
        log(f"    QR render failed: {e}", "WARN")
    print()
    print(f"  {_c(_DIM, 'Pair this token in the Super Research app:')}")
    print(f"       {_c(_ACCENT, '•')} Scan QR  {_c(_DIM, '→')}  chat → Connect → Scan QR")
    print(f"       {_c(_ACCENT, '•')} or Paste {_c(_DIM, '→')}  Account → Pipeline Connection")
    print()
    # Capture the start timestamp BEFORE clearing so that an app-side claim
    # racing with our clear (claim writes `linkedAt: serverTimestamp()`) still
    # falls within the freshness window below. Clock-skew tolerance of 30s
    # further absorbs server/client drift.
    setup_started_ms = int(time.time() * 1000)

    # Critical: clear any stale link fields from a previous --pair run BEFORE
    # we start watching. If the user unlinked via the app but the release write
    # silently failed, `linkedUid` might still be present — we'd read it here
    # and auto-advance as if paired. Resetting the fields on every --pair
    # guarantees the email NEVER appears until the user does a live pair.
    try:
        _firebase_db.collection("research_tokens").document(token).update({
            "linkedUid": "",
            "linkedEmail": "",
            "linkedAt": None,
        })
        log("Cleared any stale link on this token — waiting for a fresh pair from the app.", "INFO")
    except Exception as e:
        log(f"    Could not reset stale link fields: {e}", "WARN")

    # Watch the token doc — the app calls claimResearchToken after validating
    # + saving, which writes {linkedUid, linkedEmail, linkedAt} here. We
    # require ALL THREE to be present, plus linkedAt newer than this --pair
    # started (with 30s skew tolerance), so a stale pre-run claim can never
    # slip through.
    linked_uid: str | None = None
    linked_email: str | None = None
    link_deadline = time.time() + wait_minutes * 60
    tick = 0
    first_err_logged = False
    # Spinner-driven wait: poll Firestore once per 3-second window while a
    # Braille-dot frame ticks every 100ms on the same line so the terminal
    # reads as alive. Elapsed counter + Ctrl+C hint ride alongside the
    # spinner. Single \r-overwritten line — no scrolling wall of
    # "...still waiting" noise.
    wait_start_ts = time.time()
    frame_idx = 0
    POLL_EVERY_FRAMES = 30  # 30 × 100ms ≈ 3s (matches previous poll cadence)
    aborted_by_user = False

    def _rollback_unclaimed_token():
        """Delete the Firestore token doc we minted this run. Only called
        from the abort/timeout paths when no link has been confirmed, so
        there's no device doc or paired UID to worry about — the token
        doc is the only Firestore state --pair has written so far."""
        if not (new_token_minted and _firebase_db):
            return
        try:
            _firebase_db.collection("research_tokens").document(token).delete()
            log(f"Rolled back unclaimed token doc in Firestore: {token[:8]}…", "INFO")
        except Exception as e:
            log(f"Cleanup of unclaimed token doc failed (non-fatal): {e}", "WARN")

    try:
        while time.time() < link_deadline and linked_uid is None:
            # Poll Firestore on frame 0 of each window
            if frame_idx % POLL_EVERY_FRAMES == 0:
                try:
                    doc = _firebase_db.collection("research_tokens").document(token).get()
                    if doc.exists:
                        data = doc.to_dict() or {}
                        _uid = data.get("linkedUid") or ""
                        _email = data.get("linkedEmail") or ""
                        _at = data.get("linkedAt")
                        # linkedAt is a Firestore Timestamp — convert to ms-since-epoch.
                        _at_ms = 0
                        if _at is not None:
                            try:
                                _at_ms = int(_at.timestamp() * 1000)
                            except Exception:
                                _at_ms = 0
                        # Accept the link only when all three fields are present AND
                        # the claim is newer than this --pair started (prevents a
                        # cached pre-run claim from auto-advancing). 30s skew tolerance
                        # for server/client clock drift.
                        if _uid and _email and _at_ms >= setup_started_ms - 30_000:
                            linked_uid = _uid
                            linked_email = _email
                            break
                except Exception as e:
                    if not first_err_logged:
                        log(f"    Link poll error (continuing): {e}", "WARN")
                        first_err_logged = True
            # Advance spinner
            frame = _SPINNER_FRAMES[frame_idx % len(_SPINNER_FRAMES)]
            elapsed = int(time.time() - wait_start_ts)
            mm, ss = divmod(elapsed, 60)
            sys.stdout.write(
                f"\r  {_c(_ACCENT, frame)}  {_c(_DIM, 'waiting for the app to pair…')}   "
                f"{_c(_DIM, f'{mm:d}:{ss:02d}')}   {_c(_DIM, '(Ctrl+C to cancel)')}    "
            )
            sys.stdout.flush()
            frame_idx += 1
            await asyncio.sleep(0.1)
    except (asyncio.CancelledError, KeyboardInterrupt):
        # User Ctrl+C'd mid-wait. Swallow so we can run cleanup, then
        # exit cleanly with a "cancelled" message instead of a noisy
        # traceback. linked_uid is still None → rollback below handles it.
        aborted_by_user = True

    # Clear the spinner line so the next print starts clean
    sys.stdout.write("\r" + " " * 78 + "\r")
    sys.stdout.flush()

    if linked_uid is None:
        _rollback_unclaimed_token()
        print()
        if aborted_by_user:
            print(f"  {_c(_WARN, 'Pair cancelled.')}")
        else:
            print(f"  {_c(_WARN, 'Timed out waiting for app pairing.')}")
        if new_token_minted:
            print(f"  {_c(_DIM, '     No token saved locally. Re-run to start fresh.')}")
        else:
            print(f"  {_c(_DIM, '     Your existing token is kept — re-run to try again.')}")
        print(f"  {_c(_DIM, 'Re-run when ready:')}  {_c(_BOLD, 'python research.py --pair')}")
        return

    # Prefer the email written by the scanner; fall back to Firebase Auth.
    if not linked_email:
        try:
            from firebase_admin import auth as fb_auth
            user_obj = fb_auth.get_user(linked_uid)
            linked_email = user_obj.email or linked_uid[:8]
        except Exception:
            linked_email = linked_uid[:8]

    # Link confirmed — now safe to persist the token to research_config.json.
    # Held off until this point so a mid-pair Ctrl+C / timeout leaves no
    # researchToken on disk (the Firestore token doc is torn down by the
    # abort path above when newly minted).
    _persist_research_token_locally(token)
    # Pin the paired uid locally so --serve's heartbeat can mirror into the
    # device doc without re-reading Firestore. Also upsert the device doc so
    # the app's Account page + sidebar see this PC immediately.
    save_device_config(paired_uid=linked_uid)
    write_device_doc(linked_uid, token, device_name=chosen_device_name)

    print()
    print(f"  {_c(_OK, '✓')}  Linked to {_c(_BOLD, linked_email or '—')}")
    print()

    # ══════════════════════════════════════════════════════════════════════
    # [2/4] ON STARTUP — ask whether to enable On Startup mode. We only
    #       CAPTURE the answer here; the actual arming (schtasks install
    #       + detached daemon-loop spawn) happens in step 4 AFTER logins
    #       succeed, so an aborted login can't leave Firestore with
    #       supervised=true while platforms are half-logged-in.
    # ══════════════════════════════════════════════════════════════════════
    _setup_step(2, 4, "On Startup")
    print(f"  {_c(_DIM, 'Keep the backend running in the background?')}")
    print(f"  {_c(_DIM, 'It will auto-start when you log in and stay alive through crashes')}")
    print(f"  {_c(_DIM, 'and reboots. You can turn it off anytime with --retire.')}")
    print()
    enable_on_startup = False
    try:
        _startup_typed = await asyncio.to_thread(
            input, f"  {_c(_ACCENT, '>')}  Enable On Startup? {_c(_DIM, '[Y/n]')}: ",
        )
        _ans = _startup_typed.strip().lower()
        if _ans in ("", "y", "yes"):
            enable_on_startup = True
    except (EOFError, KeyboardInterrupt):
        # Ctrl+C at the prompt — safer default is to skip arming, so a
        # user who meant to abort doesn't end up with a silently-armed
        # supervisor if they continue through the rest of --pair anyway.
        enable_on_startup = False
        print()
    print()
    if enable_on_startup:
        print(f"  {_c(_OK, '✓')}  On Startup will be enabled after the logins finish.")
    else:
        print(f"  {_c(_DIM, '     Skipped. You will run --serve manually in step 4.')}")
        print(f"  {_c(_DIM, '     Enable later with:')}  {_c(_BOLD, 'python research.py --resurrect')}")
    print()

    # ══════════════════════════════════════════════════════════════════════
    # [3/4] BROWSER LOGINS — open 7 platform tabs and wait for real auth.
    # ══════════════════════════════════════════════════════════════════════
    _setup_step(3, 4, "Browser logins")
    print(f"  {_c(_DIM, 'Walking through logins one platform at a time.')}")
    print(f"  {_c(_DIM, 'Already-logged-in platforms (from a prior setup) are auto-detected.')}")
    print("")

    browser = Browser(profile_dir, headless=False)
    await browser.start()

    # CUA client for visual double-verification. Best-effort: if no key is
    # available, Step 2 falls back to Playwright-only verification (same as
    # before). With a key present, each platform has to pass BOTH Playwright
    # DOM checks AND CUA vision before Step 2 clears it — matches Phase 0
    # init rigor.
    _setup_cua_client = None
    _setup_cua_api_key = os.environ.get("CUA_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if _setup_cua_api_key:
        try:
            import anthropic as _anthropic
            _setup_cua_client = _anthropic.Anthropic(api_key=_setup_cua_api_key)
            log("Setup Step 2: CUA vision verifier enabled — each platform will be double-checked.", "INFO")
        except Exception as e:
            log(f"Setup Step 2: Could not init CUA client ({e}) — Playwright-only verification.", "WARN")
    else:
        log("Setup Step 2: No CUA_API_KEY — Playwright-only verification (less rigorous).", "WARN")

    services = [
        ("ChatGPT",        "https://chatgpt.com",           "chatgpt"),
        ("Gemini",         "https://gemini.google.com",     "gemini"),
        ("Claude",         "https://claude.ai",             "claude"),
        ("NotebookLM",     "https://notebooklm.google.com", "notebooklm"),
        ("YouTube Studio", "https://studio.youtube.com",    "youtube"),
        ("Gmail",          "https://mail.google.com",       "gmail"),
        ("Google Docs",    "https://docs.google.com",       "gdocs"),
    ]
    # ── Sequential per-platform login (cookie fast-path + press-Enter) ─────
    # SETUP-2026-04-19: replaces the earlier bulk-open-then-batch-verify
    # flow. Two problems with the old approach: (1) opening 7 tabs within
    # a few seconds reads as a robotic burst to Cloudflare scoring, and
    # (2) asking the user to juggle 7 simultaneous login flows is
    # overwhelming. New flow walks the list in order — one platform at a
    # time, cookie-check first, tab-open only on miss, close after verify
    # so the browser shows just the current target.
    pad = max(len(n) for n, _u, _k in services)
    results: dict[str, bool] = {}
    cancelled = False
    all_ok = False

    def _emit_row(_name, ok, label=""):
        mark = _c(_OK, "[ok]") if ok else _c(_WARN, "[--]")
        suffix = f"  {_c(_DIM, label)}" if label else ""
        print(f"        {mark}  {_name.ljust(pad)}{suffix}")

    def _push_firestore_progress():
        if not (_firebase_db and token):
            return
        try:
            _firebase_db.collection("research_tokens").document(token).update({
                "logins": {k: bool(results.get(k, False)) for _n, _u, k in services},
                "setupState": "ready" if all(results.get(k, False) for _n, _u, k in services) else "awaiting_login",
                "lastSetupCheck": int(time.time()),
            })
        except Exception:
            pass

    for idx, (name, url, key) in enumerate(services):
        # Cookie fast-path — trusted signal, no tab open, no CUA call.
        try:
            cookie_ok = await cookie_login_hit(browser, key)
        except Exception:
            cookie_ok = False
        if cookie_ok:
            results[key] = True
            _emit_row(name, True, "already logged in (session cookie found)")
            _push_firestore_progress()
            continue

        # Stagger tab opens just like the probe paths — a user clicking
        # through bookmarks takes a beat between each one.
        if idx > 0:
            await asyncio.sleep(random.uniform(2.5, 4.5))

        try:
            tab = await browser.new_tab(url)
        except Exception as e:
            log(f"    Failed to open {name}: {e}", "WARN")
            results[key] = False
            _emit_row(name, False, f"could not open ({e})")
            _push_firestore_progress()
            continue

        # SPA hydration — matches Phase 0 / probe timing. CUA misreads
        # the neutral loading shell as a login wall if we peek too early.
        await asyncio.sleep(4.0)

        print("")
        print(f"  {_c(_BOLD, name)}  {_c(_DIM, '— log in on the tab that just opened.')}")

        platform_ok = False
        while True:
            try:
                await asyncio.to_thread(input, f"  {_c(_ACCENT, '>')}  Press Enter when done ")
            except (EOFError, KeyboardInterrupt):
                print("")
                log("Setup cancelled by user", "INFO")
                cancelled = True
                try:
                    await tab.close()
                except Exception:
                    pass
                break

            # Re-check cookies first (cheap). Login flow landed? Cookie's there.
            try:
                cookie_ok = await cookie_login_hit(browser, key)
            except Exception:
                cookie_ok = False
            if cookie_ok:
                platform_ok = True
                break

            # Fall through to the two-layer verify: Playwright DOM + CUA.
            try:
                playwright_ok = await verify_login(tab, key, strict=True)
            except Exception:
                playwright_ok = False
            if not playwright_ok:
                print(f"  {_c(_WARN, 'Not logged in yet — finish the flow and press Enter again.')}")
                continue

            if not _setup_cua_client:
                platform_ok = True
                break
            try:
                cua_ok = await verify_login_cua(tab, key, _setup_cua_client)
            except Exception as e:
                log(f"    CUA verify error for {key}: {e}", "WARN")
                cua_ok = False
            if cua_ok:
                platform_ok = True
                break
            print(f"  {_c(_WARN, 'DOM passed but CUA disagreed — try the login again and press Enter.')}")

        if cancelled:
            break

        try:
            await tab.close()
        except Exception:
            pass

        results[key] = platform_ok
        _emit_row(name, platform_ok)
        _push_firestore_progress()

    if not cancelled:
        all_ok = all(results.get(k, False) for _n, _u, k in services)
    last_results = dict(results)

    _push_firestore_progress()
    await browser.close()

    print("")
    if all_ok:
        # ══════════════════════════════════════════════════════════════════════
        # [4/4] READY — pair is complete. If the user opted into On Startup
        #       back in step 2, arm the supervisor NOW (deferred from step 2
        #       so an aborted login couldn't leave Firestore flagged as
        #       supervised while platforms were half-logged-in). Final
        #       message branches on whether the supervisor is live.
        # ══════════════════════════════════════════════════════════════════════
        _setup_step(4, 4, "Ready")
        print(f"  {_c(_OK, '✓')}  Paired with {_c(_BOLD, linked_email or '—')}")
        print(f"  {_c(_OK, '✓')}  All {len(services)} platforms logged in")
        print(f"  {_c(_OK, '✓')}  Browser closed")

        supervised_armed = False
        if enable_on_startup:
            print()
            # Spin while arming — the 5s daemon-loop detection wait would
            # otherwise look frozen.
            async with _async_spinner_ctx("Enabling On Startup"):
                ok, pid, info, killed_serves = await asyncio.to_thread(_arm_supervisor_quiet)
            if ok:
                supervised_armed = True
                _write_supervised_flag(True)
                print(f"  {_c(_OK, '✓')}  Scheduled Task pinned to login ({_SUPERVISOR_TASK_NAME})")
                if killed_serves:
                    plural = "es" if killed_serves != 1 else ""
                    print(f"  {_c(_DIM, f'     Stopped {killed_serves} running --serve process{plural} to free port 8000.')}")
                if pid is not None and info == "already running":
                    print(f"  {_c(_OK, '✓')}  Backend already running (PID {pid})")
                elif pid is not None:
                    print(f"  {_c(_OK, '✓')}  Backend started (PID {pid}, running in background)")
                else:
                    print(f"  {_c(_WARN, '⚠')}  {info or 'Backend did not appear within 5s'}")
                    print(f"  {_c(_DIM, '     The scheduled task still fires at next login as a fallback.')}")
                print(f"  {_c(_OK, '✓')}  Synced to the Super Research app")
            else:
                if info == "non-Windows":
                    print(f"  {_c(_WARN, '⚠')}  On Startup is Windows-only today.")
                    print(f"  {_c(_DIM, '     macOS / Linux desktop: tracked as task #355 (launchd + systemd-user).')}")
                else:
                    print(f"  {_c(_WARN, '⚠')}  Could not enable On Startup: {info}")
                print(f"  {_c(_DIM, '     Run manually with:')}  {_c(_BOLD, 'python research.py --resurrect')}")
        else:
            # User chose N to On Startup. Enforce that: remove any
            # previously-installed scheduled task + kill any running
            # daemon-loop / serve from a prior pair, so "N" genuinely means
            # "nothing is running in the background — I will run --serve
            # manually". Without this, a leftover supervisor from an
            # earlier --pair/--resurrect keeps respawning --serve and the
            # user can't tell where the backend is coming from.
            print()
            async with _async_spinner_ctx("Enforcing unsupervised mode"):
                task_info, killed_procs = await asyncio.to_thread(_disarm_supervisor_quiet)
            _write_supervised_flag(False)
            if task_info == "removed":
                print(f"  {_c(_OK, '✓')}  Removed leftover Scheduled Task ({_SUPERVISOR_TASK_NAME})")
            elif task_info == "missing":
                print(f"  {_c(_DIM, '     No scheduled task was installed.')}")
            elif task_info == "non-Windows":
                pass  # silent — schtasks is Windows-only
            else:
                print(f"  {_c(_WARN, '⚠')}  schtasks teardown: {task_info}")
            if killed_procs:
                plural = "es" if killed_procs != 1 else ""
                print(f"  {_c(_OK, '✓')}  Stopped {killed_procs} leftover backend process{plural}")
            else:
                print(f"  {_c(_DIM, '     No backend processes were running.')}")

        print()
        if supervised_armed:
            print(f"  {_c(_BOLD + _ACCENT, '  The bond is forged.')}  {_c(_DIM, 'The backend is live — running in the background.')}")
            _render_next_actions([
                ("python research.py --retire", "disable On Startup"),
                ("python research.py --unpair", "fully disconnect this machine"),
            ])
        else:
            print(f"  {_c(_BOLD + _ACCENT, '  The bond is forged.')}  {_c(_DIM, 'Start the backend in this terminal to accept jobs:')}")
            print()
            print(f"       {_c(_BOLD, 'python research.py --serve')}")
            _render_next_actions([
                ("python research.py --resurrect", "enable On Startup (auto-start in background)"),
                ("python research.py --unpair", "fully disconnect this machine"),
            ])
    else:
        print()
        print(f"  {_c(_WARN, '━' * 62)}")
        print(f"  {_c(_WARN, 'Setup cancelled — not all platforms logged in yet.')}")
        print(f"  {_c(_WARN, '━' * 62)}")
        print("")
        if last_results:
            print(f"  {_c(_DIM, 'Last check:')}")
            for name, _u, key in services:
                ok = last_results.get(key)
                mark = _c(_OK, "[ok]") if ok else _c(_DIM, "[  ]")
                print(f"        {mark}  {name if ok else _c(_DIM, name)}")
            print("")
        print(f"  {_c(_DIM, 'Your token is saved. Re-run when ready:')}")
        print(f"        {_c(_BOLD, 'python research.py --pair')}")
        print("")


# ── Supervised mode (--resurrect / --retire) ───────────────────────────
#
# Installs a Windows Scheduled Task that auto-starts `python research.py
# --serve` at user logon, so a reboot (Windows Update, power blip, crash)
# doesn't need manual re-launch. Paired with the backend's existing startup
# auto-retry (research.py:8099 detects an incomplete checkpoint and resumes),
# this makes the pipeline survive unexpected downtime end-to-end.
#
# Task is scoped to the CURRENT USER — never elevated to SYSTEM — so it
# retains access to the user's Chrome profile / cookies, which Playwright
# needs for the logged-in agents.

_SUPERVISOR_TASK_NAME = "SuperResearchBackend"


def _enumerate_research_py_procs() -> list[tuple[int, str, str]]:
    """Return [(pid, cmdline, role), ...] for every python.exe whose
    command line references this script. role ∈ {'daemon-loop', 'serve',
    'other'}. Single source of truth for --resurrect (what's running
    before I spawn?) and --retire (what do I need to kill?).

    Matches on "research.py" substring so subprocess invocations launched
    from different cwd styles (absolute, relative, with/without quotes)
    all get caught. Safe on non-Windows — returns [] when wmic is absent."""
    try:
        ps = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'",
             "get", "processid,commandline", "/format:list"],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return []
    entries: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in (ps.stdout or "").splitlines():
        line = line.strip()
        if not line:
            if cur:
                entries.append(cur); cur = {}
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            cur[k.strip()] = v.strip()
    if cur:
        entries.append(cur)
    results: list[tuple[int, str, str]] = []
    for e in entries:
        cmdline = e.get("CommandLine", "")
        if "research.py" not in cmdline:
            continue
        try:
            pid = int(e.get("ProcessId", ""))
        except ValueError:
            continue
        if "--daemon-loop" in cmdline:
            role = "daemon-loop"
        elif "--serve" in cmdline:
            role = "serve"
        else:
            role = "other"
        results.append((pid, cmdline, role))
    return results


def _kill_pids(pids: list[int]) -> int:
    """taskkill /F each PID. Returns count that successfully terminated.
    Silent on individual failures — caller can re-enumerate to confirm."""
    killed = 0
    for pid in pids:
        try:
            r = subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode == 0:
                killed += 1
        except Exception:
            pass
    return killed


def run_daemon_loop(port: int = 8000):
    """Wrapper that keeps `--serve` alive. The scheduled task installed by
    --resurrect invokes this instead of --serve directly so that the
    backend restarts automatically on ANY exit — clean shutdown from the
    Stop button (which calls os._exit to force Chromium cleanup), crashes,
    upstream failures, anything. Without this, --resurrect only fires the
    process once per logon, which defeats the "supervised" promise.

    Loops forever with a 5s delay between restarts. Exits on
    KeyboardInterrupt OR on SIGTERM/taskkill (so --retire can stop
    the live loop without requiring a reboot). The --serve child
    process is NOT killed — it stays alive so the current pipeline
    finishes, and the user manages it manually from then on."""
    import sys as _sys
    import subprocess as _subprocess
    import time as _time

    script_path = str(Path(__file__).resolve())
    python_exe = _sys.executable
    # When --resurrect spawns daemon-loop detached (DETACHED_PROCESS), this
    # wrapper runs with no console. A naked `subprocess.run` on python.exe
    # (a console app) then forces Windows to ALLOCATE A NEW CONSOLE for
    # every --serve spawn — and every restart pops another visible terminal
    # window. CREATE_NO_WINDOW suppresses that allocation, and redirecting
    # stdio to the log files keeps uvicorn's output tailable without a
    # window ever appearing.
    _NO_WINDOW = getattr(_subprocess, "CREATE_NO_WINDOW", 0x08000000)
    _log_dir = Path(script_path).parent
    _serve_log = _log_dir / "backend.log"
    _serve_err = _log_dir / "backend.err.log"
    restarts = 0
    while True:
        try:
            log(f"[daemon-loop] Starting --serve (restart #{restarts})")
            with open(_serve_log, "ab") as _out, open(_serve_err, "ab") as _err:
                result = _subprocess.run(
                    [python_exe, script_path, "--serve", "--port", str(port)],
                    stdin=_subprocess.DEVNULL,
                    stdout=_out,
                    stderr=_err,
                    creationflags=_NO_WINDOW,
                )
            log(f"[daemon-loop] --serve exited with code {result.returncode}")
        except KeyboardInterrupt:
            log("[daemon-loop] Interrupted — exiting wrapper")
            return
        except Exception as e:
            log(f"[daemon-loop] Subprocess launch failed: {e}", "WARN")
        restarts += 1
        log(f"[daemon-loop] Restarting in 5s…")
        try:
            _time.sleep(5)
        except KeyboardInterrupt:
            log("[daemon-loop] Interrupted during sleep — exiting wrapper")
            return


def _write_supervised_flag(enabled: bool):
    """Push the Supervised flag to the device doc so the frontend can
    branch watchdog copy. Best-effort — if Firebase isn't reachable we still
    succeed because the scheduled task is the actual source of truth."""
    if not _firebase_db:
        return
    paired_uid = load_paired_uid()
    device_id = load_device_id()
    if not (paired_uid and device_id):
        log("Device not paired — skipping Firestore flag update.", "WARN")
        return
    try:
        _firebase_db.collection("users").document(paired_uid) \
            .collection("devices").document(device_id).update({
                "supervised": bool(enabled),
            })
        log(f"Supervised flag = {enabled} written to device doc.")
    except Exception as e:
        log(f"Could not update supervised flag: {e}", "WARN")


def _apply_supervisor_respawn_policy() -> "tuple[bool, str]":
    """Layer recurring trigger + restart-on-failure onto an existing
    SuperResearchBackend Scheduled Task. schtasks /SC ONLOGON does not
    expose Repetition or RestartCount via command-line, so we shell out
    to PowerShell once the task is created to set them.

    PT5M repetition + MultipleInstances=IgnoreNew → max ~5-min offline
    gap if daemon-loop dies for any reason (clean exit, Ctrl+C, crash).
    RestartCount=3 + RestartInterval=PT1M backstops non-zero failure
    exits with up to 3 retries spaced 1 minute apart.

    Returns (ok, msg). Best-effort: failure leaves the bare /SC ONLOGON
    behavior intact (one-shot at logon, no auto-respawn mid-session).
    """
    import subprocess as _subprocess
    ps = (
        "$ErrorActionPreference='Stop'; "
        f"$t = Get-ScheduledTask -TaskName '{_SUPERVISOR_TASK_NAME}'; "
        "$t.Triggers[0].Repetition.Interval = 'PT5M'; "
        "$t.Settings.RestartCount = 3; "
        "$t.Settings.RestartInterval = 'PT1M'; "
        "$t.Settings.StartWhenAvailable = $true; "
        f"Set-ScheduledTask -TaskName '{_SUPERVISOR_TASK_NAME}' "
        "-Trigger $t.Triggers[0] -Settings $t.Settings | Out-Null"
    )
    try:
        result = _subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "PS exit non-zero").strip()
        return True, "applied"
    except Exception as e:
        return False, f"PS error: {e}"


def _arm_supervisor_quiet() -> tuple[bool, int | None, str, int]:
    """Install the SuperResearchBackend scheduled task AND spawn a detached
    daemon-loop. No terminal narration — callers do their own.

    Returns (installed_ok, pid_or_None, info, killed_serve_count):
      • installed_ok         — schtasks install succeeded
      • pid_or_None          — daemon-loop pid if live-detected within 5s
      • info:
          - "non-Windows"    — platform not supported
          - "already running" — daemon-loop was already live; pid reflects that
          - ""               — fresh spawn detected within 5s
          - "<error string>" — failure (schtasks error, Popen failed, spawn
                               took > 5s to appear, etc.)
      • killed_serve_count   — number of plain --serve processes we had to
                               stop to free port 8000 for the supervised
                               child. Callers warn the user since the other
                               terminal's --serve died silently.

    installed_ok=True + pid=None means the scheduled task is installed but
    the live spawn did not appear — the next login will still fire it, so
    On Startup mode is enabled for the future even if this turn didn't
    catch the process handoff."""
    import sys as _sys
    import subprocess as _subprocess
    import platform as _platform
    import time as _time

    if _platform.system() != "Windows":
        return False, None, "non-Windows", 0

    python_exe = _sys.executable
    script_path = str(Path(__file__).resolve())
    task_run = f'"{python_exe}" "{script_path}" --daemon-loop'

    cmd = [
        "schtasks", "/Create",
        "/TN", _SUPERVISOR_TASK_NAME,
        "/TR", task_run,
        "/SC", "ONLOGON",
        "/RL", "LIMITED",
        "/IT",
        "/F",
    ]
    try:
        result = _subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        return False, None, f"schtasks error: {e}", 0
    if result.returncode != 0:
        return False, None, (result.stderr or result.stdout or "schtasks returned non-zero").strip(), 0

    # Layer respawn policy (PT5M repetition + restart-on-failure) onto the
    # freshly-created task — best-effort; failure leaves bare /SC ONLOGON.
    _apply_supervisor_respawn_policy()

    procs = _enumerate_research_py_procs()
    daemon_pid = next((pid for pid, _cmd, role in procs if role == "daemon-loop"), None)
    if daemon_pid is not None:
        return True, daemon_pid, "already running", 0

    plain_serve_pids = [pid for pid, _cmd, role in procs if role == "serve"]
    killed_serve_count = 0
    if plain_serve_pids:
        killed_serve_count = _kill_pids(plain_serve_pids)

    _DETACHED = getattr(_subprocess, "DETACHED_PROCESS", 0x00000008)
    _NEWGROUP = getattr(_subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    try:
        _subprocess.Popen(
            [python_exe, script_path, "--daemon-loop"],
            creationflags=_DETACHED | _NEWGROUP,
            stdout=_subprocess.DEVNULL,
            stderr=_subprocess.DEVNULL,
            stdin=_subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception as e:
        return True, None, f"spawn failed: {e}", killed_serve_count

    deadline = _time.time() + 5.0
    while _time.time() < deadline:
        _time.sleep(0.5)
        for pid, _cmd, role in _enumerate_research_py_procs():
            if role == "daemon-loop":
                return True, pid, "", killed_serve_count
    return True, None, "daemon-loop did not appear within 5s", killed_serve_count


def _disarm_supervisor_quiet() -> tuple[str, int]:
    """Inverse of _arm_supervisor_quiet. Removes the Scheduled Task AND
    kills every daemon-loop + --serve process. No terminal narration —
    callers do their own.

    Shared by the --pair N-branch (enforce "user said unsupervised") and
    any future "reset supervisor" entry point. run_retire / run_unpair
    still inline their own narration-rich versions since their step
    reporting differs.

    Returns (task_info, killed_count):
      • task_info: "removed" | "missing" | "non-Windows" | error string
      • killed_count: number of daemon-loop + serve procs stopped
    """
    import subprocess as _subprocess
    import platform as _platform
    import time as _time

    task_info = "non-Windows"
    if _platform.system() == "Windows":
        cmd = ["schtasks", "/Delete", "/TN", _SUPERVISOR_TASK_NAME, "/F"]
        try:
            result = _subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                task_info = "removed"
            elif "cannot find the file" in (result.stdout + result.stderr).lower():
                task_info = "missing"
            else:
                task_info = (result.stderr or result.stdout or "non-zero exit").strip()
        except Exception as e:
            task_info = f"schtasks error: {e}"

    self_pid = os.getpid()
    killed_total = 0
    deadline = _time.time() + 8.0
    while True:
        procs = [p for p in _enumerate_research_py_procs() if p[0] != self_pid]
        daemon_pids = [pid for pid, _cmd, role in procs if role == "daemon-loop"]
        serve_pids = [pid for pid, _cmd, role in procs if role == "serve"]
        if not daemon_pids and not serve_pids:
            break
        killed_total += _kill_pids(daemon_pids) + _kill_pids(serve_pids)
        if _time.time() >= deadline:
            break
        _time.sleep(0.5)
    return task_info, killed_total


def run_resurrect():
    """Install a Windows Scheduled Task that launches `python research.py
    --serve` at user logon. Idempotent — re-running overwrites the existing
    task. Prints actionable output on success/failure."""
    import sys as _sys
    import subprocess as _subprocess
    import platform as _platform

    _branded_header("resurgam", _BOLD + _BRIGHT, "the backend rises")

    if _platform.system() != "Windows":
        print()
        print(f"  {_c(_WARN, 'Only supported on Windows today.')}")
        print(f"  {_c(_DIM, 'macOS / Linux desktop: cross-platform background runners are tracked')}")
        print(f"  {_c(_DIM, 'as task #355 (launchd + systemd-user). See PERSISTENCE-RECIPE.md.')}")
        return

    python_exe = _sys.executable
    script_path = str(Path(__file__).resolve())
    # Use the full path to python.exe so the task runs even if PATH isn't set
    # up for the scheduler's session. Quote both to tolerate spaces.
    # Launch the daemon-loop wrapper (not --serve directly) so the backend
    # auto-restarts on any exit — including the os._exit(0) that the Stop
    # button calls for Chromium cleanup. Without this, the scheduled task
    # only fires once per logon and the backend stays dead after Stop.
    task_run = f'"{python_exe}" "{script_path}" --daemon-loop'

    # Initialize Firebase so the flag write later succeeds. Cheap no-op if
    # the sa file is missing — we just skip the flag.
    init_firebase()

    # Context strip — show device / pairing / current supervisor state before
    # the user watches us rearrange any of them.
    paired_uid = load_paired_uid()
    device_id = load_device_id()
    paired_email = _fetch_paired_email(paired_uid)
    currently_supervised = _detect_supervised()
    _render_context_strip([
        ("Device",    _c(_BOLD, device_id or "(not paired)")),
        ("Paired to", _c(_BOLD, paired_email or (paired_uid[:8] + "…") if paired_uid else "(not paired)")),
        ("On Startup", _c(_OK, "on") if currently_supervised else _c(_DIM, "off → enabling")),
    ])

    # ── [1/4] Pre-flight ──
    _setup_step(1, 4, "Pre-flight")
    if not paired_uid:
        print(f"  {_c(_WARN, '⚠')} Device not paired yet.")
        print(f"  {_c(_DIM, '     Run')} {_c(_BOLD, 'python research.py --pair')} {_c(_DIM, 'first, then retry --resurrect.')}")
        return
    print(f"  {_c(_OK, '✓')}  Pairing complete on this machine")

    # ── [2/4] Scheduling auto-start ──
    _setup_step(2, 4, "Scheduling auto-start")
    cmd = [
        "schtasks", "/Create",
        "/TN", _SUPERVISOR_TASK_NAME,
        "/TR", task_run,
        "/SC", "ONLOGON",
        "/RL", "LIMITED",       # keep user privileges (Chrome profile access)
        "/IT",                  # interactive — required for Playwright headed mode
        "/F",                   # overwrite existing
    ]
    try:
        result = _subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        print(f"  {_c(_WARN, '⚠')}  Failed to run schtasks: {e}")
        return

    if result.returncode != 0:
        print(f"  {_c(_WARN, '⚠')}  schtasks returned non-zero status.")
        if result.stderr.strip():
            print(f"  {_c(_DIM, '     stderr:')}")
            for line in result.stderr.strip().splitlines():
                print(f"       {line}")
        return

    print(f"  {_c(_OK, '✓')}  Scheduled Task pinned to login ({_SUPERVISOR_TASK_NAME})")
    print(f"  {_c(_DIM, '     Executes:')} {task_run}")

    # Layer respawn policy onto the task — PT5M repetition + restart-on-failure.
    _ok, _msg = _apply_supervisor_respawn_policy()
    if _ok:
        print(f"  {_c(_OK, '✓')}  Respawn policy applied (5-min repetition + restart-on-failure)")
    else:
        print(f"  {_c(_WARN, '⚠')}  Could not apply respawn policy: {_msg}")
        print(f"  {_c(_DIM, '     Backend still spawns at next login as a fallback.')}")

    # ── [3/4] Firestore sync ──
    _setup_step(3, 4, "Firestore sync")
    _write_supervised_flag(True)
    print(f"  {_c(_OK, '✓')}  Synced to the Super Research app")

    # ── [4/4] Handoff — activate the supervisor NOW, not at next logon ──
    # Without this, --resurrect only schedules the task and leaves the
    # backend on whatever the user had before. Active supervised mode
    # needs --daemon-loop running so --serve is supervised. Steps:
    #   (a) detect an already-running daemon-loop (re-run = no-op),
    #   (b) taskkill any plain --serve so port 8000 is free for the
    #       supervised child,
    #   (c) spawn --daemon-loop DETACHED + CREATE_NEW_PROCESS_GROUP so
    #       it outlives this call and doesn't inherit our console,
    #   (d) verify the spawn actually worked by re-polling until the
    #       daemon-loop PID appears (so we don't print "started" for
    #       a child that crashed on import).
    _setup_step(4, 4, "Handoff")
    import time as _time
    procs = _enumerate_research_py_procs()
    daemon_pid = next((pid for pid, _cmd, role in procs if role == "daemon-loop"), None)
    plain_serve_pids = [pid for pid, _cmd, role in procs if role == "serve"]

    if daemon_pid is not None:
        print(f"  {_c(_OK, '✓')}  Backend already running (PID {daemon_pid}) — nothing to spawn")
    else:
        if plain_serve_pids:
            killed = _kill_pids(plain_serve_pids)
            plural = "es" if killed != 1 else ""
            print(f"  {_c(_DIM, f'     Stopped {killed} running --serve process{plural} to free port 8000.')}")
        _DETACHED = getattr(_subprocess, "DETACHED_PROCESS", 0x00000008)
        _NEWGROUP = getattr(_subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        try:
            _subprocess.Popen(
                [python_exe, script_path, "--daemon-loop"],
                creationflags=_DETACHED | _NEWGROUP,
                stdout=_subprocess.DEVNULL,
                stderr=_subprocess.DEVNULL,
                stdin=_subprocess.DEVNULL,
                close_fds=True,
            )
        except Exception as e:
            print(f"  {_c(_WARN, '⚠')}  Could not start backend: {e}")
            print(f"  {_c(_DIM, '     The scheduled task still fires at next login.')}")
        else:
            spawned_pid = None
            with _sync_spinner_ctx("Starting backend"):
                deadline = _time.time() + 5.0
                while _time.time() < deadline:
                    _time.sleep(0.5)
                    for pid, _cmd, role in _enumerate_research_py_procs():
                        if role == "daemon-loop":
                            spawned_pid = pid
                            break
                    if spawned_pid is not None:
                        break
            if spawned_pid is not None:
                print(f"  {_c(_OK, '✓')}  Backend started (PID {spawned_pid}, running in background)")
            else:
                print(f"  {_c(_WARN, '⚠')}  Backend did not appear within 5s — check backend.err.log.")
                print(f"  {_c(_DIM, '     The scheduled task still fires at next login as a fallback.')}")

    print()
    print(f"  {_c(_BOLD + _BRIGHT, '  The supervisor holds watch.')}  {_c(_DIM, '--serve respawns on any exit.')}")
    _render_next_actions([
        ("python research.py --retire", "disable On Startup"),
    ])


def run_retire():
    """Disable On Startup — completely. Idempotent: succeeds whether or not
    the scheduled task and backend are currently running.

    Full-reset semantics: after --retire the machine is back to "nothing
    related to research.py is running in the background". If a pipeline was
    in-flight under the supervised --serve, it aborts — that's the deliberate
    cost of a clean undo. Re-run --serve yourself to bring the backend back,
    or --resurrect to re-enable On Startup.

    Three-step reset:
      1. Delete the Windows Scheduled Task so daemon-loop won't auto-start
         at next login.
      2. Kill every running daemon-loop AND every --serve process, looping
         for up to 8s so a mid-enumeration respawn (daemon-loop spawns
         --serve every ~5s between deaths) still gets caught.
      3. Flip the Firestore On Startup flag to off + verify stragglers."""
    import subprocess as _subprocess
    import platform as _platform

    _branded_header("requiescat", _BOLD + _RED, "let the loop rest")

    if _platform.system() != "Windows":
        print()
        print(f"  {_c(_WARN, 'Only supported on Windows today.')}")
        return

    init_firebase()

    # Context strip — what's about to get torn down.
    paired_uid = load_paired_uid()
    device_id = load_device_id()
    paired_email = _fetch_paired_email(paired_uid)
    currently_supervised = _detect_supervised()
    _render_context_strip([
        ("Device",     _c(_BOLD, device_id or "(not paired)")),
        ("Paired to",  _c(_BOLD, paired_email or (paired_uid[:8] + "…") if paired_uid else "(not paired)")),
        ("On Startup", _c(_OK, "on") if currently_supervised else _c(_DIM, "off — nothing to undo")),
    ])

    # Short-circuit: if nothing is armed and nothing is running, there's
    # nothing to retire. Walking through all 3 steps just to print "Nothing
    # bound / No processes running" 3 times is noise — tell the user directly.
    import time as _time
    self_pid = os.getpid()
    running_now = any(role in ("daemon-loop", "serve")
                      for pid, _cmd, role in _enumerate_research_py_procs()
                      if pid != self_pid)
    if not currently_supervised and not running_now:
        print()
        print(f"  {_c(_DIM, 'Nothing to retire — On Startup is already off and no backend is running.')}")
        _render_next_actions([
            ("python research.py --resurrect", "enable On Startup"),
        ])
        return

    # ── [1/3] Unbinding schedule ──
    _setup_step(1, 3, "Unbinding schedule")
    cmd = [
        "schtasks", "/Delete",
        "/TN", _SUPERVISOR_TASK_NAME,
        "/F",
    ]
    try:
        result = _subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        print(f"  {_c(_WARN, '⚠')}  Failed to run schtasks: {e}")
        return

    # Exit code 1 with a "does not exist" message means the task wasn't
    # installed to begin with — that's fine, we still clear the flag.
    not_installed = (
        result.returncode != 0
        and "ERROR: The system cannot find the file specified." in (result.stdout + result.stderr)
    )
    if result.returncode == 0:
        print(f"  {_c(_OK, '✓')}  Scheduled Task removed ({_SUPERVISOR_TASK_NAME})")
    elif not_installed:
        print(f"  {_c(_DIM, '     Nothing bound — task was not installed.')}")
    else:
        print(f"  {_c(_WARN, '⚠')}  schtasks returned non-zero status.")
        if result.stderr.strip():
            print(f"  {_c(_DIM, '     stderr:')}")
            for line in result.stderr.strip().splitlines():
                print(f"       {line}")

    # ── [2/3] Stopping backend ──
    # The daemon-loop respawns --serve every ~5s between deaths, so a
    # single-shot enumerate+kill misses any --serve that happened to be
    # respawning at the wrong moment. Loop for up to 8s, re-enumerating
    # each tick. Always kill daemon-loop first so it can't respawn a
    # freshly-killed --serve. `self_pid` is excluded in case --retire
    # was itself launched through the supervisor.
    _setup_step(2, 3, "Stopping backend")
    killed_daemon_total = 0
    killed_serve_total = 0
    deadline = _time.time() + 8.0
    last_survivors: list[tuple[int, str, str]] = []
    with _sync_spinner_ctx("Stopping backend — waiting for processes to exit"):
        while True:
            procs = [p for p in _enumerate_research_py_procs() if p[0] != self_pid]
            daemon_pids = [pid for pid, _cmd, role in procs if role == "daemon-loop"]
            serve_pids = [pid for pid, _cmd, role in procs if role == "serve"]
            if not daemon_pids and not serve_pids:
                last_survivors = procs  # only 'other' left, which we don't touch
                break
            killed_daemon_total += _kill_pids(daemon_pids)
            killed_serve_total += _kill_pids(serve_pids)
            if _time.time() >= deadline:
                last_survivors = [p for p in _enumerate_research_py_procs() if p[0] != self_pid]
                break
            _time.sleep(0.5)

    if killed_daemon_total:
        plural = "es" if killed_daemon_total != 1 else ""
        print(f"  {_c(_OK, '✓')}  Stopped {killed_daemon_total} daemon-loop process{plural}")
    else:
        print(f"  {_c(_DIM, '     No daemon-loop processes were running.')}")
    if killed_serve_total:
        plural = "s" if killed_serve_total != 1 else ""
        print(f"  {_c(_OK, '✓')}  Stopped {killed_serve_total} --serve process{plural}")
    else:
        print(f"  {_c(_DIM, '     No --serve processes were running.')}")

    # ── [3/3] Firestore sync + verification ──
    _setup_step(3, 3, "Firestore sync")
    _write_supervised_flag(False)
    print(f"  {_c(_OK, '✓')}  Synced to the Super Research app")

    stragglers = [(pid, role) for pid, _cmd, role in last_survivors if role in ("daemon-loop", "serve")]
    print()
    if stragglers:
        print(f"  {_c(_WARN, '⚠')}  {len(stragglers)} related process(es) would not terminate:")
        for pid, role in stragglers:
            print(f"       {_c(_BOLD, f'PID {pid}')}  ({role})")
        print(f"  {_c(_DIM, '       Kill them from Task Manager or re-run --retire.')}")
    else:
        print(f"  {_c(_BOLD + _RED, '  Silence.')}  {_c(_DIM, 'No research.py process remains.')}")
    _render_next_actions([
        ("python research.py --resurrect", "re-enable On Startup"),
    ])


def run_unpair():
    """Fully disconnect this machine from Super Research — opposite of --pair.

    Semantics: after --unpair, this PC appears NOWHERE in the Super Research
    app. The device doc under the user account is deleted, the research_token
    doc is revoked project-wide, local pairing config (token + deviceId +
    pairedUid) is wiped. A subsequent --pair mints a fresh token and
    registers a new device from scratch — there's no quiet "rejoin" path
    that resurrects the old identity.

    Preserved on disk (delete manually for a truly clean machine):
      • Chrome profile at ~/.super-research/browser-profile/ (your logins)
      • Pipeline history in queues/ + tracks/
      • firebase-service-account.json (needed to re-pair)

    This is the destructive counterpart to the app's "unlink" action, which
    only clears linkedUid on the token doc and leaves the device/token
    themselves live. --unpair is what the user runs when they're done with
    Super Research on this PC entirely.

    Five-step reset (order matters — config wipe FIRST to stop a
    daemon-loop-respawned --serve from recreating the device doc moments
    after step 3 deletes it):
      1. Wipe local research_config.json (+ legacy pipe_config.json) and
         zero in-memory caches. A respawned --serve now reads empty config
         and bails in write_device_doc's `not uid or not token` guard.
      2. Remove the scheduled task; kill every daemon-loop + serve process.
         With config already wiped, lingering processes are harmless.
      3. Delete users/{uid}/devices/{deviceId} so the device vanishes from
         the Account page device list.
      4. Delete research_tokens/{token} so the token is gone project-wide.
      5. Verify nothing survived."""
    import subprocess as _subprocess
    import platform as _platform
    import time as _time

    _branded_header("absolvo", _BOLD + _ACCENT, "the bond dissolves")

    # Load context BEFORE we nuke local state — the load_* helpers read
    # research_config.json, which step 4 deletes. init_firebase must run
    # before any Firestore delete so _firebase_db is live.
    init_firebase()
    token = load_research_token()
    paired_uid = load_paired_uid()
    device_id = load_device_id()
    paired_email = _fetch_paired_email(paired_uid)

    # NOTE: no "nothing to do" short-circuit here even when local config is
    # missing. A prior --unpair (or manual config wipe) can leave orphan
    # daemon-loop + serve processes and a scheduled task behind — those are
    # the root cause of the "paired-but-serve-crash-looping" state. We want
    # --unpair to ALWAYS run step 1 (process kill + schtasks removal) so
    # re-running it is a guaranteed-clean cleanup. Steps 2-4 already no-op
    # gracefully when the relevant state is missing.

    # Context strip — what's about to vanish.
    _render_context_strip([
        ("Device",    _c(_BOLD, device_id or "(unknown)")),
        ("Paired to", _c(_BOLD, paired_email or (paired_uid[:8] + "…") if paired_uid else "(not paired)")),
        ("Token",     _c(_BOLD, (token[:8] + "…") if token else "(none)")),
    ])

    total = 5

    # ── [1/5] Wipe local config FIRST ──
    # Critical ordering: research_config.json must disappear BEFORE we kill
    # + delete Firestore docs. A daemon-loop respawns --serve on a 5s loop
    # (research.py:14495); if we killed processes first there's a window
    # where a freshly-spawned --serve reads still-valid config, calls
    # write_device_doc (which uses set({...}, merge=True) → CREATES), and
    # resurrects the device doc moments after we deleted it. The user saw
    # the tile "remove and readd" because of exactly this race. With the
    # config wiped first, any respawned serve's load_paired_uid / token
    # return None, so write_device_doc early-returns on the
    # `not uid or not token` guard (research.py:792).
    _setup_step(1, total, "Wiping local pairing config")
    wiped = []
    try:
        if RESEARCH_CONFIG_PATH.exists():
            RESEARCH_CONFIG_PATH.unlink()
            wiped.append(RESEARCH_CONFIG_PATH.name)
    except Exception as e:
        print(f"  {_c(_WARN, '⚠')}  Could not delete {RESEARCH_CONFIG_PATH.name}: {e}")
    try:
        if _LEGACY_PIPE_CONFIG_PATH.exists():
            _LEGACY_PIPE_CONFIG_PATH.unlink()
            wiped.append(_LEGACY_PIPE_CONFIG_PATH.name)
    except Exception:
        pass
    # Zero in-memory state too, so anything still running in this process
    # can't re-read pre-wipe values from the global caches.
    global _research_token, _device_id, _device_paired_uid
    _research_token = None
    _device_id = None
    _device_paired_uid = None
    if wiped:
        print(f"  {_c(_OK, '✓')}  Deleted: {', '.join(wiped)}")
    else:
        print(f"  {_c(_DIM, '     No local config files to wipe.')}")

    # ── [2/5] Stop supervisor + serve ──
    _setup_step(2, total, "Stopping running processes")
    if _platform.system() == "Windows":
        cmd = ["schtasks", "/Delete", "/TN", _SUPERVISOR_TASK_NAME, "/F"]
        try:
            result = _subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                print(f"  {_c(_OK, '✓')}  Scheduled Task removed ({_SUPERVISOR_TASK_NAME})")
            elif "cannot find the file" in (result.stdout + result.stderr):
                print(f"  {_c(_DIM, '     No scheduled task was installed.')}")
            else:
                print(f"  {_c(_WARN, '⚠')}  schtasks returned non-zero — continuing.")
        except Exception as e:
            print(f"  {_c(_WARN, '⚠')}  schtasks error (continuing): {e}")

    # Loop-until-clean pattern so a daemon-loop mid-respawn of --serve
    # still gets fully caught.
    self_pid = os.getpid()
    killed_total = 0
    deadline = _time.time() + 8.0
    with _sync_spinner_ctx("Stopping backend — waiting for processes to exit"):
        while True:
            procs = [p for p in _enumerate_research_py_procs() if p[0] != self_pid]
            daemon_pids = [pid for pid, _cmd, role in procs if role == "daemon-loop"]
            serve_pids = [pid for pid, _cmd, role in procs if role == "serve"]
            if not daemon_pids and not serve_pids:
                break
            killed_total += _kill_pids(daemon_pids) + _kill_pids(serve_pids)
            if _time.time() >= deadline:
                break
            _time.sleep(0.5)
    if killed_total:
        plural = "es" if killed_total != 1 else ""
        print(f"  {_c(_OK, '✓')}  Stopped {killed_total} backend process{plural}")
    else:
        print(f"  {_c(_DIM, '     No backend processes were running.')}")

    # ── [3/5] Delete device doc ──
    _setup_step(3, total, "Removing device from your account")
    if _firebase_db and paired_uid and device_id:
        try:
            _firebase_db.collection("users").document(paired_uid) \
                .collection("devices").document(device_id).delete()
            print(f"  {_c(_OK, '✓')}  Deleted users/{paired_uid[:8]}…/devices/{device_id}")
        except Exception as e:
            print(f"  {_c(_WARN, '⚠')}  Device doc delete failed: {e}")
    elif not _firebase_db:
        print(f"  {_c(_WARN, '⚠')}  Firebase unreachable — skipped.")
        print(f"  {_c(_DIM, '        Remove the device via the Account page when you can.')}")
    else:
        print(f"  {_c(_DIM, '     No paired account on this machine — nothing to remove.')}")

    # ── [4/5] Delete token doc ──
    _setup_step(4, total, "Revoking token from project")
    if _firebase_db and token:
        try:
            _firebase_db.collection("research_tokens").document(token).delete()
            print(f"  {_c(_OK, '✓')}  Deleted research_tokens/{token[:8]}…")
        except Exception as e:
            print(f"  {_c(_WARN, '⚠')}  Token doc delete failed: {e}")
    elif not _firebase_db:
        print(f"  {_c(_WARN, '⚠')}  Firebase unreachable — token doc left in place.")
        print(f"  {_c(_DIM, '        Re-run --unpair with network to finish.')}")
    else:
        print(f"  {_c(_DIM, '     No token on this machine — nothing to revoke.')}")

    # ── [5/5] Verify ──
    _setup_step(5, total, "Confirming silence")
    stragglers = [p for p in _enumerate_research_py_procs()
                  if p[0] != self_pid and p[2] in ("daemon-loop", "serve")]
    if stragglers:
        print(f"  {_c(_WARN, '⚠')}  {len(stragglers)} related process(es) would not terminate:")
        for pid, _cmd, role in stragglers:
            print(f"       {_c(_BOLD, f'PID {pid}')}  ({role})")
        print(f"  {_c(_DIM, '       Kill them from Task Manager or re-run --unpair.')}")
    else:
        print(f"  {_c(_OK, '✓')}  No research.py process remains")

    print()
    print(f"  {_c(_BOLD + _ACCENT, '  The bond dissolves.')}  {_c(_DIM, 'This machine is no longer paired.')}")
    print()
    print(f"  {_c(_DIM, 'Preserved on disk (remove manually for a fully clean slate):')}")
    print(f"       {_c(_DIM, '• Chrome profile at ~/.super-research/browser-profile/  (your logins)')}")
    print(f"       {_c(_DIM, '• Research history in queues/ and tracks/')}")
    print(f"       {_c(_DIM, '• firebase-service-account.json  (needed to re-pair)')}")
    _render_next_actions([
        ("python research.py --pair", "reconnect this machine (mints a fresh token)"),
    ])


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Deep Research Pipeline")
    parser.add_argument("topic", nargs="?", help="Research topic")
    parser.add_argument("--pdf", action="append", default=[], help="PDF to attach (Phase 1)")
    parser.add_argument("--brief-file", "-b", help="Existing brief file (skip Phase 1)")
    parser.add_argument("--email", "-e", help="Email for Phase 6 delivery")
    parser.add_argument("--api-key", "-k", help="CUA API key")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--pair", action="store_true", help="First-time login setup")
    parser.add_argument("--resume", "-r", help="Resume from a previous queue directory (name or full path)")
    parser.add_argument("--serve", action="store_true", help="Start web app API server")
    parser.add_argument("--port", type=int, default=8000, help="Server port (default: 8000)")
    parser.add_argument("--resurrect", action="store_true",
        help="Enable On Startup: auto-start the backend at login and keep it running in the background")
    parser.add_argument("--retire", action="store_true",
        help="Disable On Startup: remove the auto-start scheduled task and stop the background backend")
    parser.add_argument("--unpair", action="store_true",
        help="Fully disconnect this machine from Super Research (inverse of --pair): deletes token + device doc + local config")
    parser.add_argument("--daemon-loop", action="store_true",
        help="Internal: wrapper that keeps --serve alive by relaunching it on any exit. Used by the On Startup scheduled task.")
    args = parser.parse_args()

    if args.resurrect:
        run_resurrect()
        return

    if args.retire:
        run_retire()
        return

    if args.unpair:
        run_unpair()
        return

    if args.daemon_loop:
        run_daemon_loop(args.port)
        return

    if args.pair:
        asyncio.run(run_pair(str(PROFILE_DIR)))
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
