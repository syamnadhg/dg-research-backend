"""Presentation helpers for a run's progress — shared by the bridge + the CLI.

The backend stores per-phase links as a ``links.{kind}`` map of objects
(``{url, label, phase, verified}``) on the research doc, written incrementally
as each phase completes. Two facts shape how a poller consumes them (both
code-verified against research.py):

  * link entries carry NO per-link timestamp (only a ``phase`` int), and
  * a per-phase link write does NOT bump the doc's ``updatedAt``,

so a watermark on ``updatedAt`` would miss link additions. The robust contract
is therefore: surface the CURRENT flattened link set every poll and let the
consumer dedup by ``(runId, kind)``. ``flatten_links`` produces that ordered,
deduped view; the bridge attaches it to status/updates responses and the CLI
``watch`` loop prints kinds it hasn't seen yet.
"""

from __future__ import annotations

import re
from typing import Any

# Canonical emission order (phase 1 → 5) for presenting a run's links.
KIND_ORDER = [
    "brief",
    "chatgpt", "gemini", "claude",
    "notebooklm", "audio", "audio_file",
    "youtube",
    "doc", "podcast",
]

# A run in one of these states will not progress further — a watcher stops here.
TERMINAL_STATUSES = frozenset({
    "completed", "stopped", "error", "archived",
    "terminated_by_user_discard", "stopped_by_watchdog",
    "paused_backend_restart_failed",
})

# The legacy aggregate arrays (links.phase1 / links.phase2 …) duplicate the
# per-kind objects; skip them so a kind isn't streamed twice.
_PHASE_ARRAY_KEY = re.compile(r"^phase\d+$")


def is_terminal(status: Any) -> bool:
    return status in TERMINAL_STATUSES


def _sort_key(event: dict[str, Any]) -> tuple[int, int]:
    try:
        ki = KIND_ORDER.index(event["kind"])
    except ValueError:
        ki = len(KIND_ORDER)
    ph = event["phase"] if isinstance(event["phase"], int) else 99
    return (ph, ki)


def flatten_links(links: Any) -> list[dict[str, Any]]:
    """Flatten a ``links.{kind}`` map into an ordered, url-deduped event list.

    Returns ``[{kind, phase, url, label}, …]`` sorted by (phase, canonical kind
    order). Tolerant of object-valued and bare-string-valued entries; skips the
    legacy ``phaseN`` aggregate arrays and any entry without a url.
    """
    if not isinstance(links, dict):
        return []
    out: list[dict[str, Any]] = []
    for kind, v in links.items():
        if _PHASE_ARRAY_KEY.match(str(kind)):
            continue
        if isinstance(v, dict):
            url, label, phase = v.get("url"), v.get("label") or kind, v.get("phase")
        elif isinstance(v, str):
            url, label, phase = v, kind, None
        else:
            continue
        if not url or not isinstance(url, str):
            continue
        out.append({"kind": kind, "phase": phase, "url": url, "label": label})
    # Sort FIRST, then dedup by url — so on a duplicate url the canonical
    # (phase, KIND_ORDER)-first entry wins deterministically, not whichever kind
    # Firestore happened to serialize first.
    out.sort(key=_sort_key)
    seen_urls: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for e in out:
        if e["url"] in seen_urls:
            continue
        seen_urls.add(e["url"])
        deduped.append(e)
    return deduped
