#!/usr/bin/env python3
"""Once-daily Super Research skill-update notice (2026-07-06, user directive:
"when there is an update, it must check once a day and let the user know").

Runs as a Hermes `no_agent` cron job (name "sr-update-notice", schedule
"every 1d") armed by the /sr skill via the same do-not-relay directive block
as the streaming watchdog. Each daily tick asks the bridge for a FRESH PyPI
read (`/version?fresh=1`) and prints ONE nudge line when a newer skill
version is published — the `no_agent` contract treats empty stdout as
silent, so a current install posts nothing, ever. De-dup state lives in a
sibling file so the same version is announced exactly once (a NEWER version
re-announces).

Self-cleanup: if the bridge is unreachable for 3 consecutive daily ticks
(e.g. `disconnect` removed it), the job removes its OWN entry from
<HERMES_HOME>/cron/jobs.json — matched by name, never touching other jobs —
so it can't spam "Script not found" or poll a dead bridge forever. Mirrors
sr_attention_poll's conventions (port env, jobs.json removal, state sibling).
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

try:
    import fcntl  # POSIX advisory file lock. The Hermes host is always POSIX;
except ImportError:  # None elsewhere (e.g. a Windows test import) → lock-free write.
    fcntl = None

_JOB_NAME = "sr-update-notice"
_TIMEOUT = 10
_MAX_STRIKES = 3  # consecutive bridge-unreachable daily ticks before self-removal


def _base() -> str:
    # ⛔ EMPTY IS UNSET, NOT BAD. `os.environ.get(name, default)` returns "" for a
    # variable that is SET AND EMPTY — a shape a shell exports readily — and the
    # bridge treats that as unset. Without the strip-and-test this copy called it
    # a bad value instead, which is the same disagreement between the bridge and
    # its clients that this whole rule exists to remove.
    raw = (os.environ.get("SUPER_AGENT_BRIDGE_PORT") or "").strip()
    port = 9876
    if raw:
        try:
            val = int(raw)
            if 1 <= val <= 65535:
                port = val
        except ValueError:
            pass
    return f"http://127.0.0.1:{port}"


def _hermes_home() -> Path:
    """<HERMES_HOME> — this script lives at <HERMES_HOME>/scripts/<this file>."""
    return Path(__file__).resolve().parent.parent


def _state_path() -> Path:
    return Path(__file__).resolve().parent / ".sr_update_notice.state.json"


def _log(msg: str) -> None:
    """One line in the watcher's log FILE (owner, 2026-09-25) — never stdout, which
    the runtime posts into the chat word for word. Same file and the same override
    (`SUPER_AGENT_WATCHER_LOG`) as sr_attention_poll._log_path. Never raises."""
    try:
        raw = (os.environ.get("SUPER_AGENT_WATCHER_LOG") or "").strip()
        path = Path(raw) if raw else Path.home() / ".super-agent" / "watcher.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        with open(path, "ab") as fh:
            fh.write(f"{stamp} update-notice[{os.getpid()}] {msg}\n"
                     .encode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — diagnostics only
        pass


def _load_state() -> dict:
    try:
        data = json.loads(_state_path().read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        _state_path().write_text(json.dumps(state), "utf-8")
    except Exception:
        pass  # best-effort; a missed save just re-announces next day (rare)


def _version_gt(a: str, b: str) -> bool:
    """True if `a` is strictly newer than `b`. Tolerant zero-padded numeric
    compare; False on any parse error (never nag off a garbage version)."""
    def parse(v: str) -> list:
        out = []
        for chunk in str(v).split("."):
            digits = ""
            for ch in chunk:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            out.append(int(digits) if digits else 0)
        return out
    try:
        pa, pb = parse(a), parse(b)
        n = max(len(pa), len(pb))
        pa += [0] * (n - len(pa))
        pb += [0] * (n - len(pb))
        return pa > pb
    except Exception:
        return False


def _remove_cron_entry(job_name: str) -> bool:
    """Remove the job named ``job_name`` from <HERMES_HOME>/cron/jobs.json
    (atomic, best-effort). Only ever drops the entry we created.

    ⛔⛔ UNDER THE SAME LOCK AS EVERY OTHER WRITER, WITH ITS OWN TEMP NAME (owner,
    2026-09-25). This was the one writer of jobs.json that took no `.jobs.lock`
    and used a SHARED temp name — so a gateway save (or sr.py's arming write)
    landing between our read and our replace was silently thrown away, and two
    writers could publish each other's half-written file. It now does exactly
    what sr.py `_arm_stream_cron` and sr_attention_poll `_remove_cron_entry` do:
    the advisory flock for the whole read-modify-write, a per-process temp file."""
    path = _hermes_home() / "cron" / "jobs.json"
    lock_fd = None
    try:
        lock_fd = open(path.parent / ".jobs.lock", "a+", encoding="utf-8")
    except OSError:
        lock_fd = None  # best-effort; proceed without the cross-process lock
    if lock_fd is not None and fcntl is not None:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except OSError:
            pass
    try:
        try:
            data = json.loads(path.read_text("utf-8"))
        except Exception:
            return False
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            return False
        kept = [j for j in jobs if not (isinstance(j, dict) and j.get("name") == job_name)]
        if len(kept) == len(jobs):
            return False
        data["jobs"] = kept
        tmp = path.with_suffix(".json.sr-tmp.%d" % os.getpid())
        try:
            tmp.write_text(json.dumps(data), "utf-8")
            os.replace(tmp, path)  # atomic; Hermes re-reads jobs.json each tick
            return True
        except Exception:
            try:
                tmp.unlink()
            except OSError:
                pass
            return False
    finally:
        if lock_fd is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            lock_fd.close()


def main() -> int:
    state = _load_state()
    try:
        with urllib.request.urlopen(f"{_base()}/version?fresh=1", timeout=_TIMEOUT) as r:
            body = json.loads(r.read().decode("utf-8"))
    except Exception:
        # Bridge unreachable — likely disconnected. Strike; self-remove after 3
        # consecutive daily misses so a dead install never spams the chat.
        strikes = int(state.get("strikes", 0)) + 1
        if strikes >= _MAX_STRIKES:
            removed = _remove_cron_entry(_JOB_NAME)
            _log(f"bridge unreachable {strikes} days running — own cron row "
                 f"{'removed' if removed else 'not found'}")
            try:
                _state_path().unlink()
            except Exception:
                pass
        else:
            _save_state({**state, "strikes": strikes})
        return 0  # silent — empty stdout posts nothing
    state["strikes"] = 0

    current = str(body.get("agent") or "")
    latest = str(body.get("agentLatest") or "")
    if latest and current and _version_gt(latest, current) \
            and state.get("announced") != latest:
        # ⛔ SAY IT, THEN RECORD IT (owner, 2026-09-25). The version was recorded as
        # announced BEFORE the print, so a tick killed in between (a broken stdout
        # pipe, the cron harness dying) left a state file claiming a notice nobody
        # was sent — and a given version is announced exactly once, so it never
        # was. Printed first, the same window costs a repeat instead — the rule the
        # streaming watcher already follows ("speak first, then commit").
        print(f"⬆️ A Super Research skill update is available (v{current} → v{latest}) "
              f"— say “update” and I'll install it.")
        _log(f"printed the update notice v{current} → v{latest}")
        state["announced"] = latest
    _save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
