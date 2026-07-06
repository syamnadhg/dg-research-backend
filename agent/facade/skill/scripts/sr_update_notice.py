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
import urllib.request
from pathlib import Path

_JOB_NAME = "sr-update-notice"
_TIMEOUT = 10
_MAX_STRIKES = 3  # consecutive bridge-unreachable daily ticks before self-removal


def _base() -> str:
    raw = os.environ.get("SUPER_AGENT_BRIDGE_PORT", "9876")
    try:
        port = int(raw)
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        port = 9876
    return f"http://127.0.0.1:{port}"


def _hermes_home() -> Path:
    """<HERMES_HOME> — this script lives at <HERMES_HOME>/scripts/<this file>."""
    return Path(__file__).resolve().parent.parent


def _state_path() -> Path:
    return Path(__file__).resolve().parent / ".sr_update_notice.state.json"


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
    (atomic, best-effort). Only ever drops the entry we created."""
    path = _hermes_home() / "cron" / "jobs.json"
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
    try:
        tmp = path.with_suffix(".json.sr-tmp")
        tmp.write_text(json.dumps(data), "utf-8")
        os.replace(tmp, path)  # atomic; Hermes re-reads jobs.json each tick
        return True
    except Exception:
        return False


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
            _remove_cron_entry(_JOB_NAME)
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
        state["announced"] = latest
        _save_state(state)
        print(f"⬆️ A Super Research skill update is available (v{current} → v{latest}) "
              f"— say “update” and I'll install it.")
    else:
        _save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
