"""Instant delivery: run a chat's watcher NOW, through Hermes's own CLI.

⭐⭐ WHY THIS EXISTS (owner, 2026-09-25). Hermes v0.21.3 hands every scheduled
message to a queue that only its gateway's housekeeping loop sends — once a
minute, and up to ~6 minutes under load — and it never re-checks a queued message
before sending it. On top of that our watcher's "every 1m" interval runs every ~2
minutes. On 2026-09-24 a TRUE "✓ Signed in" sat in that queue and was delivered
19 s after the person had logged out.

⭐ THE DECISION: instant delivery WITHOUT changing Hermes. When the bridge has news
for a chat it runs ``hermes cron run <that chat's sr-stream job id>`` itself. Run
from outside the gateway, Hermes executes the job synchronously in that process
and sends directly — its queue is never involved (hermes_cli/cron.py `_job_action`
forces a synchronous stateless run and prints "Ran now: succeeded/failed"). The
watcher's own cron tick stays exactly as it was, as the fallback. The queue itself
is left alone (owner decision 2 of 2026-09-25).

⛔⛔ THE RULES THIS FILE KEEPS, each one a way the push could itself go wrong:
  • NEVER ON THE CALLER'S THREAD. `request` returns at once; the job lookup, the
    CLI run, every retry and every sleep happen on a daemon thread. A bridge HTTP
    handler that parks a note must not wait on a Telegram send.
  • ONE RUN IN FLIGHT PER JOB. A second request for a job that is already running
    is folded into ONE follow-up run after it, never a second concurrent run —
    two runs of one watcher would race each other's de-dup state.
  • RE-CHECKED IMMEDIATELY BEFORE EVERY SPAWN, retries included. The caller hands
    in `still_valid`; if it answers False (the person logged out, the note was
    already taken) nothing is run. "Nothing false or stale may ever be sent."
  • BOUNDED. A hard timeout on the CLI; a short, finite retry ladder only for
    "already being fired" (the gateway's ticker holds the job's claim).
  • READ-ONLY on Hermes's state. jobs.json is read, never written — the job's id
    is found by its origin, and Hermes's own CLI does everything else.
  • A SILENT NO-OP when the chat runtime is not Hermes or its CLI is absent. The
    cron tick still delivers; this only ever makes it sooner.
  • LOGGED, every step, so a late or missing message can be root-caused from
    ~/.super-agent/bridge.log alone: trigger, job ids, spawn, the CLI's own result
    line, duration.

⚠ WHAT THIS DOES NOT CLOSE (2026-09-25 — decision 2 leaves the queue alone). The
push's run and the gateway's own tick read the same `/updates`, and whichever
reads first takes the note. A tick that gets there first — a capture a few seconds
before its minute, while the CLI is still starting — sends it through Hermes's
queue, as late as before. The push then sees "busy" and finds nothing left; the
log names that case ("the gateway's own tick held this job …") rather than
calling it "no longer current".

⛔ OFF UNTIL `serve()` ARMS IT. Handler-level unit tests never start `serve()`, so
nothing in the suite can reach a real Hermes install on the machine running it —
the same reason the remote-login auto-poller is started from `serve()` only.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import prefs

log = logging.getLogger(__name__)

# ⛔ LONG ENOUGH FOR A COLD CLI START + THE WATCHER'S OWN 30 s BRIDGE CALL + ONE
# SEND; short enough that a wedged CLI cannot pin a thread for good.
_TIMEOUT_SECONDS = 90.0

# ⛔ ONLY "ALREADY BEING FIRED" IS RETRIED, and on this ladder. The gateway's ticker
# can hold the job's claim for as long as its own queued send waits (~60 s, more
# under load), so the ladder reaches past that — and stops, because the ticker's
# own run is by then delivering whatever it took.
_RETRY_DELAYS = (5.0, 15.0, 30.0, 60.0)

_WATCHER_SCRIPT = "sr_attention_poll.py"
_SHIM_RE = re.compile(r"sr_poll_[A-Za-z0-9_]+\.py")
_RESULT_MAX = 200
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")

# The CLI's own words, matched loosely (case-folded) so a wording tweak upstream
# degrades to "unknown" in the log rather than to a wrong outcome.
_BUSY_MARKERS = ("already being fired", "already running", "already in progress",
                 "being fired")
_MISSING_MARKERS = ("no such job", "job not found", "not found")


def enabled() -> bool:
    """``DG_AGENT_PUSH`` (default ON) — the in-field kill-switch, same shape as
    ``DG_AGENT_AUTOSTART``. Off → every request is a no-op and the watcher's own
    cron tick delivers, exactly as before 2026-09-25."""
    return (os.environ.get("DG_AGENT_PUSH", "1").strip().lower()
            in ("1", "true", "yes", "on"))


def origin_slug(origin: Any) -> str:
    """The chat's short id — IDENTICAL to sr.py's `_origin_slug`, so a log line
    names the same `sr-stream-<slug>` job the watcher runs under, and never the raw
    chat id (a chat id is a personal identifier; bridge.log is uploadable)."""
    if not isinstance(origin, dict):
        return "every chat"
    platform = re.sub(r"[^A-Za-z0-9]", "", str(origin.get("platform") or "")).lower()[:16] or "chat"
    key = "\x00".join((str(origin.get("platform") or ""), str(origin.get("chat_id") or ""),
                       str(origin.get("thread_id") or "")))
    return f"{platform}_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"


def _mask(line: str) -> str:
    """A CLI line fit for bridge.log: emails masked, length capped."""
    line = _EMAIL_RE.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", line or "")
    return line if len(line) <= _RESULT_MAX else line[:_RESULT_MAX - 1] + "…"


# ── where Hermes lives ────────────────────────────────────────────────────────

def _home_candidates() -> list[Path]:
    """Every plausible <HERMES_HOME>, most authoritative first — the same order
    sr.py's `_scripts_dir_candidates` uses: the runtime's own declaration
    (``$HERMES_HOME``), then the home `agent connect` recorded the skill under,
    then the default layout."""
    out: list[Path] = []

    def add(p: Path) -> None:
        if p not in out:
            out.append(p)

    env = (os.environ.get("HERMES_HOME") or "").strip()
    if env:
        add(Path(env).expanduser())
    try:
        rec = prefs.get_runtime_home()
    except Exception:  # noqa: BLE001 — prefs is best-effort
        rec = None
    if rec:
        add(Path(rec) / ".hermes")
    add(Path.home() / ".hermes")
    return out


def hermes_home() -> Path | None:
    """The <HERMES_HOME> that actually holds a cron store, or None.

    ⭐ PICK THE CANDIDATE THAT HOLDS THE EVIDENCE — `cron/jobs.json` on disk — the
    same rule sr.py applies to the watcher script. A declared home with no store
    in it is not where the watcher's job lives."""
    for c in _home_candidates():
        try:
            if (c / "cron" / "jobs.json").is_file():
                return c
        except OSError:
            continue
    return None


def hermes_cli() -> str | None:
    """Absolute path of the ``hermes`` CLI, or None.

    ⛔ PATH FIRST, THEN ~/.local/bin BY HAND. A bridge started by systemd,
    launchd or a scheduled task inherits a minimal PATH that usually omits
    ~/.local/bin — which is where a Hermes install puts its launcher."""
    found = shutil.which("hermes")
    if found:
        return os.path.abspath(found)
    bases = [Path.home()]
    try:
        rec = prefs.get_runtime_home()
    except Exception:  # noqa: BLE001
        rec = None
    if rec and Path(rec) not in bases:
        bases.append(Path(rec))
    for base in bases:
        for name in ("hermes", "hermes.exe", "hermes.cmd"):
            p = base / ".local" / "bin" / name
            try:
                if p.is_file() and (os.name == "nt" or os.access(p, os.X_OK)):
                    return str(p)
            except OSError:
                continue
    return None


def unavailable_reason() -> str | None:
    """Why a push cannot happen on this computer, or None when it can."""
    if not enabled():
        return "switched off (DG_AGENT_PUSH)"
    try:
        runtime = prefs.get_runtime()
    except Exception:  # noqa: BLE001
        runtime = None
    if runtime != "hermes":
        return f"the chat runtime is {runtime or 'not recorded'}, not Hermes"
    if hermes_cli() is None:
        return "no `hermes` CLI on this computer"
    if hermes_home() is None:
        return "no Hermes cron store (cron/jobs.json) found"
    return None


def available() -> bool:
    return unavailable_reason() is None


# ── which job ─────────────────────────────────────────────────────────────────

def _is_watcher(job: Any) -> bool:
    """One of OUR streaming watchers: the per-chat `sr-stream-<slug>` job (its
    generated `sr_poll_<slug>.py` shim) or the legacy shared `sr-stream` job."""
    if not isinstance(job, dict):
        return False
    name = str(job.get("name") or "")
    script = str(job.get("script") or "")
    return (name == "sr-stream" or name.startswith("sr-stream-")
            or script == _WATCHER_SCRIPT or bool(_SHIM_RE.fullmatch(script)))


def _runnable(job: dict) -> bool:
    return (job.get("enabled", True) is not False and job.get("state") != "paused"
            and bool(str(job.get("id") or "").strip()))


def _same_chat(a: Any, b: Any) -> bool:
    """Platform (case-folded) and chat id — the same two fields the bridge's
    delivery gate compares, so "this chat's watcher" means one thing everywhere."""
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return False
    pa = str(a.get("platform") or "").strip().lower()
    ca = str(a.get("chat_id") or "").strip()
    return bool(pa and ca and pa == str(b.get("platform") or "").strip().lower()
                and ca == str(b.get("chat_id") or "").strip())


def watcher_jobs(home: Path | None, origin: Any) -> list[dict[str, Any]]:
    """The runnable watcher jobs that deliver to ``origin`` — or, for an
    account-wide note (``origin`` None), every watcher job on this host.

    ⛔ READ-ONLY. jobs.json is Hermes's own store and the gateway rewrites it on
    every tick; this opens it, parses it and closes it — no lock, no write. Every
    writer replaces it atomically, so a read never sees half a file."""
    if home is None:
        return []
    try:
        data = json.loads((home / "cron" / "jobs.json").read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return []
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        return []
    out = []
    for j in jobs:
        if not (_is_watcher(j) and _runnable(j)):
            continue
        if origin is not None and not _same_chat(j.get("origin"), origin):
            continue
        out.append({"id": str(j.get("id")).strip(), "name": str(j.get("name") or ""),
                    "origin": j.get("origin")})
    return out


def has_target(origin: Any) -> bool:
    """Whether a push for ``origin`` would reach any watcher at all — the gate a
    background peek checks BEFORE spending a Firestore read on news nobody could
    be sent."""
    if not PUSHER.armed or not available():
        return False
    return bool(watcher_jobs(hermes_home(), origin))


# ── running it ────────────────────────────────────────────────────────────────

def classify(returncode: int, text: str) -> tuple[str, str]:
    """(outcome, the CLI's own result line) from one `hermes cron run`.

    outcomes: ``sent`` (Ran now: succeeded) · ``failed`` (Ran now: failed) ·
    ``busy`` (the ticker holds the claim — retried) · ``missing`` (no such job) ·
    ``error`` (non-zero exit, anything else) · ``unknown`` (exit 0, unrecognised)."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]

    def pick(markers) -> str | None:
        for ln in lines:
            low = ln.lower()
            if any(m in low for m in markers):
                return ln
        return None

    busy = pick(_BUSY_MARKERS)
    if busy is not None:
        return "busy", _mask(busy)
    ran = pick(("ran now",))
    if ran is not None:
        low = ran.lower()
        return ("failed" if "fail" in low else "sent"), _mask(ran)
    missing = pick(_MISSING_MARKERS)
    if missing is not None:
        return "missing", _mask(missing)
    last = _mask(lines[-1]) if lines else f"exit {returncode}, no output"
    return ("unknown" if returncode == 0 else "error"), last


def _run_cli(cli: str, home: Path, job_id: str, timeout: float) -> tuple[str, str]:
    """One synchronous `hermes cron run <job_id>`. Never raises.

    ⛔ BYTES, DECODED HERE, NOT `text=True`: on Windows a text-mode pipe decodes
    with the ANSI code page and a "✓" in Hermes's output would raise inside the
    reader thread. `splitlines()` then takes CRLF and LF alike.
    ⛔ HERMES_HOME IS PASSED EXPLICITLY — the directory the job was found in — so
    the CLI cannot resolve a different store than the one that named the job."""
    argv = [cli, "cron", "run", job_id]
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        cp = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout, env=env,
                            check=False, **kwargs)
    except subprocess.TimeoutExpired:
        return "timeout", f"no answer in {timeout:.0f}s — the run was killed"
    except OSError as e:
        return "error", f"could not start the CLI ({type(e).__name__})"
    return classify(cp.returncode, (cp.stdout or b"").decode("utf-8", "replace"))


def _spawn_thread(target: Callable, *args: Any) -> None:
    threading.Thread(target=target, args=args, daemon=True, name="sr-push").start()


_UNAVAILABLE_SEEN: set[str] = set()
_UNAVAILABLE_LOCK = threading.Lock()


def _note_unavailable(reason: str, why: str) -> None:
    """INFO the first time a given reason stops a push, DEBUG after — a host with
    no Hermes would otherwise log the same line at every sign-in."""
    with _UNAVAILABLE_LOCK:
        first = why not in _UNAVAILABLE_SEEN
        _UNAVAILABLE_SEEN.add(why)
    (log.info if first else log.debug)("push %s: not run — %s (the watcher's own "
                                       "tick will deliver)", reason, why)


Valid = Callable[[], bool]


def _still(valid: Valid | None) -> bool:
    if valid is None:
        return True
    try:
        return bool(valid())
    except Exception as e:  # noqa: BLE001 — a check that cannot answer is a "no"
        log.debug("push re-check raised %s — treating as no longer current",
                  type(e).__name__)
        return False


class Pusher:
    """Runs watcher jobs on request, one in flight per job, coalescing the rest."""

    def __init__(self, *, runner: Callable[..., tuple[str, str]] | None = None,
                 sleeper: Callable[[float], None] | None = None,
                 spawner: Callable[..., None] | None = None,
                 home: Callable[[], Path | None] | None = None,
                 cli: Callable[[], str | None] | None = None,
                 reason_unavailable: Callable[[], str | None] | None = None,
                 retry_delays: tuple[float, ...] = _RETRY_DELAYS,
                 timeout: float = _TIMEOUT_SECONDS) -> None:
        self._run = runner or _run_cli
        self._sleep = sleeper or time.sleep
        self._spawn = spawner or _spawn_thread
        self._home = home or hermes_home
        self._cli = cli or hermes_cli
        self._why_not = reason_unavailable or unavailable_reason
        self._retry_delays = tuple(retry_delays)
        self._timeout = timeout
        self._lock = threading.Lock()
        # job id -> follow-up requests that arrived while its run was in flight.
        self._inflight: dict[str, list[tuple[str, Valid | None]]] = {}
        self.armed = False

    def request(self, origin: Any, *, reason: str, still_valid: Valid | None = None) -> bool:
        """Ask for this chat's watcher (or, origin None, every watcher) to run now.

        Returns at once. True when the request was handed to a background thread."""
        if not self.armed:
            log.debug("push %s: not armed (no serve())", reason)
            return False
        try:
            self._spawn(self._fan_out, origin, reason, still_valid)
        except Exception as e:  # noqa: BLE001 — a courtesy, never a failure
            log.info("push %s: not dispatched (%s)", reason, type(e).__name__)
            return False
        return True

    def _fan_out(self, origin: Any, reason: str, still_valid: Valid | None) -> None:
        try:
            why = self._why_not()
            if why:
                _note_unavailable(reason, why)
                return
            home, cli = self._home(), self._cli()
            if home is None or cli is None:
                _note_unavailable(reason, "Hermes disappeared between checks")
                return
            jobs = watcher_jobs(home, origin)
            scope = origin_slug(origin)
            if not jobs:
                log.info("push %s → %s: no watcher job for that chat on this computer "
                         "— nothing to run", reason, scope)
                return
            log.info("push %s → %s: %d watcher job(s): %s", reason, scope, len(jobs),
                     ", ".join(f"{j['id']} ({j['name'] or '-'})" for j in jobs))
            for j in jobs:
                self._enqueue(cli, home, j["id"], reason, still_valid)
        except Exception as e:  # noqa: BLE001 — a background courtesy never raises
            log.warning("push %s: failed before running anything (%s)", reason,
                        type(e).__name__)

    def _enqueue(self, cli: str, home: Path, job_id: str, reason: str,
                 still_valid: Valid | None) -> None:
        with self._lock:
            pending = self._inflight.get(job_id)
            if pending is not None:
                pending.append((reason, still_valid))
                coalesced = True
            else:
                self._inflight[job_id] = []
                coalesced = False
        if coalesced:
            log.info("push %s → job %s: a run is already in flight — folded into one "
                     "follow-up run after it", reason, job_id)
            return
        try:
            self._spawn(self._drive, cli, home, job_id, [(reason, still_valid)])
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self._inflight.pop(job_id, None)
            log.info("push %s → job %s: not dispatched (%s)", reason, job_id,
                     type(e).__name__)

    def _drive(self, cli: str, home: Path, job_id: str,
               todo: list[tuple[str, Valid | None]]) -> None:
        """Run the job for ``todo``, then once more for anything folded in meanwhile.

        ⛔ THE HAND-OFF IS UNDER THE LOCK: a request that arrives while this run is
        in flight is either in the list taken below or starts a fresh driver after
        the slot is released — never lost between the two."""
        try:
            while todo:
                self._attempts(cli, home, job_id, todo)
                with self._lock:
                    todo = self._inflight.get(job_id) or []
                    if todo:
                        self._inflight[job_id] = []
                    else:
                        self._inflight.pop(job_id, None)
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self._inflight.pop(job_id, None)
            log.warning("push → job %s: stopped (%s)", job_id, type(e).__name__)

    def _attempts(self, cli: str, home: Path, job_id: str,
                  todo: list[tuple[str, Valid | None]]) -> str:
        reasons = "+".join(sorted({r for r, _v in todo}))
        attempt = 0
        for delay in (0.0,) + self._retry_delays:
            if delay:
                self._sleep(delay)
            # ⛔⛔ THE RE-CHECK, IMMEDIATELY BEFORE THE SPAWN, EVERY TIME. Between
            # the event and this line the person may have logged out, or another
            # reader may already have said it; a watcher run started now would
            # then either say nothing (wasted) or — worse — say something stale.
            live = [r for r, v in todo if _still(v)]
            if not live:
                # ⛔ SAY WHO MOST LIKELY TOOK IT (2026-09-25). After a "busy" the
                # gateway's own tick held this job, and its run reads the same
                # `/updates` — so the news went out through Hermes's queue, late,
                # not "no longer current". The residual decision 2 leaves open.
                log.info("push %s → job %s: skipped — no longer current (%s)", reasons,
                         job_id,
                         "the gateway's own tick held this job and most likely took "
                         "it: that copy goes through Hermes's queue" if attempt else
                         "signed out, or a reply or the gateway's own tick already "
                         "took it")
                return "stale"
            attempt += 1
            log.info("push %s → job %s: running `hermes cron run` (attempt %d)",
                     "+".join(sorted(set(live))), job_id, attempt)
            t0 = time.monotonic()
            outcome, line = self._run(cli, home, job_id, self._timeout)
            took = time.monotonic() - t0
            log.info("push %s → job %s: %s in %.1fs — %s", "+".join(sorted(set(live))),
                     job_id, outcome, took, line)
            if outcome != "busy":
                return outcome
        log.info("push %s → job %s: still claimed by the gateway's own tick after %d "
                 "attempts — that tick delivers it, through Hermes's queue", reasons,
                 job_id, attempt)
        return "busy"


PUSHER = Pusher()


def arm() -> None:
    """Called once by `serve()`. Until then every request is a no-op."""
    PUSHER.armed = True
    why = unavailable_reason()
    if why:
        log.info("instant delivery: unavailable here — %s; the watcher's own cron "
                 "tick delivers", why)
    else:
        log.info("instant delivery: on — news runs the chat's watcher through `%s`",
                 hermes_cli())


def disarm() -> None:
    PUSHER.armed = False


def request(origin: Any, *, reason: str, still_valid: Valid | None = None) -> bool:
    """Module-level entry point the bridge calls. See `Pusher.request`."""
    return PUSHER.request(origin, reason=reason, still_valid=still_valid)
