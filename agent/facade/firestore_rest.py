"""Minimal Firestore REST client, scoped to the account session.

Reimplements just the operations the bridge needs, over the Firestore REST API
with the account's ID token as a Bearer credential — so this package needs no
google-cloud-firestore dependency and stays decoupled from the BE.

Every call here authenticates AS THE ACCOUNT USER (request.auth.uid == the
tree's userId — the owner branch), the same identity research-app/web/src/lib/
firestore.ts uses from the browser:
  * read   users/{uid}/researches          (owner of the tree)
  * read   devices where member             (ownerUid == uid OR uid in sharedWith)
  * upsert users/{uid}/researches/{rid}     (owner of the tree)
  * create devices/{deviceId}/queue/{auto}  (isDeviceMember && submittedBy == uid)
  * upsert/get/delete users/{uid}/agentSessions/{id}   (owner of the tree, #790)

The first four need NO rules change. The agentSessions ops (#790) require ONE
owner-only match block in firestore.rules — a verbatim mirror of the existing
users/{uid}/sessions block (rules v2 does not inherit the parent users/{uid}
allow to subcollections). The owner-only rule covers BOTH this bridge write
(bridge == the user) and the FE reading its own agent rows.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any, Callable

import requests

from . import config

log = logging.getLogger(__name__)


# ── typed-value (de)serialization ──────────────────────────────────────────

def _now_iso() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def to_value(v: Any) -> dict[str, Any]:
    """Encode a Python value as a Firestore typed value."""
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: to_value(x) for k, x in v.items()}}}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [to_value(x) for x in v]}}
    raise TypeError(f"unsupported Firestore value type: {type(v).__name__}")


def from_value(v: dict[str, Any]) -> Any:
    """Decode a Firestore typed value back to a Python value."""
    if "nullValue" in v:
        return None
    if "booleanValue" in v:
        return v["booleanValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        # Firestore serializes an integer-valued double (5.0) as bare `5`, which
        # json parses to int — coerce back to float to preserve the type.
        return float(v["doubleValue"])
    if "stringValue" in v:
        return v["stringValue"]
    if "timestampValue" in v:
        return v["timestampValue"]
    if "mapValue" in v:
        return {
            k: from_value(x) for k, x in v.get("mapValue", {}).get("fields", {}).items()
        }
    if "arrayValue" in v:
        return [from_value(x) for x in v.get("arrayValue", {}).get("values", [])]
    return None


def fields_to_dict(doc: dict[str, Any]) -> dict[str, Any]:
    """Decode a Firestore document's ``fields`` map into a plain dict."""
    return {k: from_value(x) for k, x in doc.get("fields", {}).items()}


def doc_id(name: str) -> str:
    """Last path segment of a Firestore resource name."""
    return name.rsplit("/", 1)[-1]


def is_pair_confirmed(d: dict[str, Any]) -> bool:
    """Whether a device doc is a usable, pair-confirmed member — mirrors the web
    app's ``isPairConfirmed`` (firestore.ts). A device must be confirmed paired
    (``pairConfirmedAt`` is True) or currently online (a positive ``lastHeartbeat``).
    The owner-unlink the app performs DELETES ``pairConfirmedAt`` (and ownerUid /
    sharedWith) but leaves the device doc, so without this gate the agent would keep
    showing — and enqueueing research to — a device the app already considers gone.
    """
    if d.get("pairConfirmedAt") is True:
        return True
    hb = d.get("lastHeartbeat")
    return isinstance(hb, (int, float)) and not isinstance(hb, bool) and hb > 0


# ── client ──────────────────────────────────────────────────────────────────

class FirestoreRest:
    """Account-scoped Firestore REST operations.

    ``token_provider`` returns a valid ID token (typically
    ``AccountSession.id_token``); we call it per request so token refresh is
    transparent, and retry once on a 401 in case it expired mid-flight.
    """

    def __init__(self, token_provider: Callable[..., str]) -> None:
        # token_provider(force: bool = False) -> id token. We call it with
        # force=True after a 401 so the retry carries a FRESHLY minted token
        # (re-sending the cached one would just 401 again).
        self._token = token_provider

    def _send(self, method: str, url: str, token: str, json_body: Any) -> Any:
        return requests.request(
            method, url,
            headers={"Authorization": f"Bearer {token}"},
            json=json_body, timeout=15,
        )

    def _request(self, method: str, url: str, *, json_body: Any = None,
                 allow_missing: bool = False) -> Any:
        resp = self._send(method, url, self._token(), json_body)
        if resp.status_code == 401:
            # Force a fresh token and retry exactly once.
            resp = self._send(method, url, self._token(force=True), json_body)
        if allow_missing and resp.status_code == 404:
            return None
        if not resp.ok:
            raise FirestoreError(
                f"{method} {url.split('/databases')[-1]} -> "
                f"HTTP {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json() if resp.content else {}

    # ── reads ──
    def list_researches(self, uid: str, *, page_size: int = 50) -> list[dict[str, Any]]:
        """List the user's research docs, NEWEST first.

        The REST documents.list endpoint, absent ``orderBy``, returns docs by
        document name (the random ``agent-<hex>`` id) — unrelated to recency — so
        a "most recent run" query over a name-ordered window would pick the wrong
        docs once the account has more than a page of researches. We order by
        createdAt desc to mirror the web app (firestore.ts orderBy createdAt desc).
        """
        url = (f"{config.FIRESTORE_BASE}/users/{uid}/researches"
               f"?pageSize={page_size}&orderBy=createdAt%20desc")
        body = self._request("GET", url)
        out: list[dict[str, Any]] = []
        for d in body.get("documents", []):
            row = fields_to_dict(d)
            row["id"] = doc_id(d.get("name", ""))
            out.append(row)
        return out

    def get_research(self, uid: str, rid: str) -> dict[str, Any] | None:
        """Read one research (chat) doc under the user's tree, or None if absent.

        Used by /status + /cancel — the decoded fields carry status/phase/links
        for status, and deviceId for routing a cancel to the right device queue.
        """
        url = f"{config.FIRESTORE_BASE}/users/{uid}/researches/{rid}"
        body = self._request("GET", url, allow_missing=True)
        if not body:
            return None
        row = fields_to_dict(body)
        row["id"] = doc_id(body.get("name", ""))
        return row

    def get_user_settings(self, uid: str) -> dict[str, Any] | None:
        """Read the account's settings doc (``users/{uid}/settings/prefs``), or
        None if the user never saved settings.

        Carries the per-account pipeline defaults (which agents, skip brief /
        podcast / video / email, podcast length, skipInitVerify) that an
        agent-fired run must honor — the same doc the web app's ``loadSettings``
        reads. allow_missing so a settings-less account reads as None (→ the run
        falls back to the pipeline defaults, same as the web app)."""
        url = f"{config.FIRESTORE_BASE}/users/{uid}/settings/prefs"
        body = self._request("GET", url, allow_missing=True)
        if not body:
            return None
        return fields_to_dict(body)

    def get_agent_session(self, uid: str, sid: str) -> dict[str, Any] | None:
        """Read the agent-session doc (#790), or None if absent/deleted.

        The bridge's heartbeat reads this to consult ``revoked`` — a user who
        taps Revoke on the agent row in the app's "Shared with" popup sets
        ``revoked: true`` here, and the bridge self-logs-out on the next tick.
        allow_missing=True so a not-yet-created / already-deleted session reads
        as None (treated as not-revoked / session-gone), never an error.
        """
        url = f"{config.FIRESTORE_BASE}/users/{uid}/agentSessions/{sid}"
        body = self._request("GET", url, allow_missing=True)
        if not body:
            return None
        row = fields_to_dict(body)
        row["id"] = doc_id(body.get("name", ""))
        return row

    def list_devices(self, uid: str) -> list[dict[str, Any]]:
        """List devices the account can reach: owned ∪ shared-to.

        Two structured queries unioned by deviceId (Firestore has no native OR
        across distinct fields). Returns each device's decoded fields + id.

        Pair-confirmed only (``is_pair_confirmed``) — matching the web app's device
        list exactly, so the agent never shows or enqueues to a device the app
        considers gone/not-ready (an owner-unlinked doc persists with
        pairConfirmedAt deleted).
        """
        seen: dict[str, dict[str, Any]] = {}
        for field, op in (("ownerUid", "EQUAL"), ("sharedWith", "ARRAY_CONTAINS")):
            query = {
                "structuredQuery": {
                    "from": [{"collectionId": "devices"}],
                    "where": {
                        "fieldFilter": {
                            "field": {"fieldPath": field},
                            "op": op,
                            "value": {"stringValue": uid},
                        }
                    },
                }
            }
            rows = self._request(
                "POST", f"{config.FIRESTORE_BASE}:runQuery", json_body=query
            )
            for entry in rows:
                doc = entry.get("document")
                if not doc:
                    continue
                did = doc_id(doc.get("name", ""))
                if did and did not in seen:
                    fields = fields_to_dict(doc)
                    fields["id"] = did
                    seen[did] = fields
        return [d for d in seen.values() if is_pair_confirmed(d)]

    # ── writes ──
    def upsert_research(self, uid: str, rid: str, fields: dict[str, Any]) -> None:
        """Create/merge the research (chat) doc under the user's tree."""
        mask = "&".join(f"updateMask.fieldPaths={k}" for k in fields)
        url = f"{config.FIRESTORE_BASE}/users/{uid}/researches/{rid}?{mask}"
        self._request(
            "PATCH", url, json_body={"fields": {k: to_value(v) for k, v in fields.items()}}
        )

    def seed_chat_messages(self, uid: str, rid: str, *, topic: str, title: str) -> None:
        """Seed the two opening chat bubbles the WEB APP writes client-side at
        run start but an agent-started run never gets: the user TOPIC bubble +
        the assistant intro ("Researching …"). Without them an agent run's in-app
        chat is missing its opening messages and renders inconsistently with a
        web-started chat (the BE pipeline only writes pipeline_events, never the
        messages subcollection; the bridge is the agent's stand-in for the
        missing web client). Mirrors the FE saveMessage doc shape exactly
        ({role, content, timestamp} at messages/{id}, ordered by timestamp).
        Deterministic ids keep it idempotent; ``intro-{rid}`` matches the web
        app's id so the FE phase_start upgrade rewrites it in place rather than
        adding a duplicate. Best-effort — callers must not let a failure fail the
        run (tiles still hydrate from events)."""
        now_ms = int(time.time() * 1000)
        label = (title or topic or "").strip()
        if len(label) > 100:
            label = label[:100].rstrip() + "…"
        intro = f'Researching **"{label}"**' if label else "Researching..."
        msgs = (
            (f"topic-{rid}", {"role": "user", "content": topic, "timestamp": now_ms}),
            (f"intro-{rid}", {"role": "assistant", "content": intro, "timestamp": now_ms + 1}),
        )
        for mid, fields in msgs:
            mask = "&".join(f"updateMask.fieldPaths={k}" for k in fields)
            url = f"{config.FIRESTORE_BASE}/users/{uid}/researches/{rid}/messages/{mid}?{mask}"
            self._request("PATCH", url, json_body={"fields": {k: to_value(v) for k, v in fields.items()}})

    def delete_research(self, uid: str, rid: str) -> None:
        """Delete a research doc under the user's own tree (owner branch).

        Used to clean up a just-created chat doc when the queue enqueue fails, so
        a failed start doesn't leave an orphan chat. Idempotent — deleting an
        absent doc is a no-op on the REST API.
        """
        url = f"{config.FIRESTORE_BASE}/users/{uid}/researches/{rid}"
        self._request("DELETE", url)

    def upsert_agent_session(self, uid: str, sid: str, fields: dict[str, Any]) -> None:
        """Create/merge the agent-session doc (#790) under the user's tree.

        A masked PATCH so passing only ``{"lastSeenAt": now}`` touches the
        heartbeat WITHOUT clobbering siblings (label/runtime/connectedAt) — the
        same idempotent create-or-merge idiom as upsert_research. The doc id is
        the host install id (prefs.get_or_create_install_id), so re-login
        overwrites the same row rather than accreting a new one.
        """
        mask = "&".join(f"updateMask.fieldPaths={k}" for k in fields)
        url = f"{config.FIRESTORE_BASE}/users/{uid}/agentSessions/{sid}?{mask}"
        self._request(
            "PATCH", url, json_body={"fields": {k: to_value(v) for k, v in fields.items()}}
        )

    def delete_agent_session(self, uid: str, sid: str) -> None:
        """Delete the agent-session doc on a clean /logout (#790). Idempotent."""
        url = f"{config.FIRESTORE_BASE}/users/{uid}/agentSessions/{sid}"
        self._request("DELETE", url)

    def enqueue_start(
        self,
        device_id: str,
        *,
        uid: str,
        research_id: str,
        topic: str,
        email: str,
        config_obj: dict[str, Any] | None = None,
        display_name: str = "",
    ) -> str:
        """Write a start doc to devices/{deviceId}/queue (the FE's contract).

        Returns the created queue doc id. The device daemon's start listener
        claims it and runs the normal pipeline.
        """
        now_ms = int(time.time() * 1000)
        payload: dict[str, Any] = {
            "uid": uid,
            "submittedBy": uid,
            "action": "start",
            "researchId": research_id,
            "topic": topic,
            "email": email,
            "config": config_obj or {},
            "timestamp": now_ms,
            "viaAgent": True,
        }
        if display_name:
            payload["submittedByDisplayName"] = display_name
        fields = {k: to_value(v) for k, v in payload.items()}
        # submittedAt as a real server-ish timestamp (the FE uses
        # serverTimestamp(); an accurate client UTC value satisfies the BE's
        # FIFO ordering + stale-queue defense, which also reads `timestamp`).
        fields["submittedAt"] = {"timestampValue": _now_iso()}
        url = f"{config.FIRESTORE_BASE}/devices/{device_id}/queue"
        body = self._request("POST", url, json_body={"fields": fields})
        return doc_id(body.get("name", ""))

    def patch_pipeline_config(self, uid: str, rid: str, pc_updates: dict[str, Any]) -> None:
        """Update specific keys UNDER ``pipelineConfig`` on a research doc.

        Uses nested updateMask field paths (``pipelineConfig.<key>``) so only the
        named sub-keys change — sibling pipelineConfig keys (agents, podcastLength,
        …) are preserved. This is how `/skip` writes skippedPhases / videoEnabled /
        emailEnabled, which the BE re-reads each phase boundary (reload_config's
        Firestore overlay, research.py ~29836).
        """
        if not pc_updates:
            return
        mask = "&".join(f"updateMask.fieldPaths=pipelineConfig.{k}" for k in pc_updates)
        url = f"{config.FIRESTORE_BASE}/users/{uid}/researches/{rid}?{mask}"
        inner = {k: to_value(v) for k, v in pc_updates.items()}
        body = {"fields": {"pipelineConfig": {"mapValue": {"fields": inner}}}}
        self._request("PATCH", url, json_body=body)

    def enqueue_cancel(self, device_id: str, *, uid: str, research_id: str,
                       owner_control: str = "") -> str:
        """Write an ``action:"cancel"`` doc to devices/{deviceId}/queue.

        Mirrors the web app's cancelQueuedPipeline (firestore.ts): the device's
        start listener matches by researchId and either drops the still-queued
        job or routes a running match to request_stop — so one cancel covers
        both states. Member-permitted (submittedBy == uid). Returns the doc id.

        ``owner_control`` ("stop" | "cancel" | "") rides on the doc as
        ``ownerControl``. "stop" routes the BE queue listener to a PRESERVE flip
        (status:"stopped", NO ``cancelled`` → the chat + partial results survive),
        exactly like the web app's owner-stop of a sharer's run — this is how the
        graceful chat stop handles a still-QUEUED run. "" keeps the legacy
        destructive self-cancel (``cancelled:true`` → the FE cascade-deletes).
        """
        now_ms = int(time.time() * 1000)
        payload: dict[str, Any] = {
            "uid": uid,
            "submittedBy": uid,
            "action": "cancel",
            "researchId": research_id,
            "timestamp": now_ms,
            "viaAgent": True,
        }
        if owner_control:
            payload["ownerControl"] = owner_control
        fields = {k: to_value(v) for k, v in payload.items()}
        fields["submittedAt"] = {"timestampValue": _now_iso()}
        url = f"{config.FIRESTORE_BASE}/devices/{device_id}/queue"
        body = self._request("POST", url, json_body={"fields": fields})
        return doc_id(body.get("name", ""))

    def write_command(self, uid: str, research_id: str, action: str, *,
                      device_id: str, extra: dict[str, Any] | None = None) -> str:
        """Write a per-run command to users/{uid}/researches/{rid}/commands — the
        SAME contract the web app's writeCommand uses (firestore.ts). The BE's
        per-run command listener (research.py _start_command_listener) consumes it.

        ``device_id`` is LOAD-BEARING: the BE listener runs as the device user and
        the security rule requires the doc's ``deviceId`` to match its device
        token — a command without it is silently permission-denied and never
        executes. ``timestamp`` is a wall-clock ms value (NOT a serverTimestamp)
        so the listener's 30s stale-on-first-snapshot gate compares correctly.
        Used for the graceful chat stop (action:"stop") + retry/skip from chat.
        Fields mirror the FE writeCommand exactly so the create rule accepts it.
        """
        now_ms = int(time.time() * 1000)
        payload: dict[str, Any] = {
            "action": action,
            "deviceId": device_id,
            "processed": False,
            "timestamp": now_ms,
        }
        if extra:
            payload.update(extra)
        fields = {k: to_value(v) for k, v in payload.items()}
        url = f"{config.FIRESTORE_BASE}/users/{uid}/researches/{research_id}/commands"
        body = self._request("POST", url, json_body={"fields": fields})
        return doc_id(body.get("name", ""))

    def update_research(self, uid: str, rid: str, patch: dict[str, Any], *,
                        delete_fields: list[str] | None = None) -> None:
        """PATCH users/{uid}/researches/{rid} with `patch` (top-level fields), and
        DELETE each field in `delete_fields` (listed in the updateMask but omitted from
        the body → Firestore removes it). The owner writing their OWN research doc — the
        SAME authoritative write the web app's Stop button does (saveResearch). This is
        what makes a chat stop reach terminal status even if the BE never consumes the
        command doc (e.g. a run paused at a decision gate). Member-permitted."""
        delete_fields = delete_fields or []
        paths = list(patch.keys()) + list(delete_fields)
        mask = "&".join(f"updateMask.fieldPaths={p}" for p in paths)
        url = f"{config.FIRESTORE_BASE}/users/{uid}/researches/{rid}?{mask}"
        fields = {k: to_value(v) for k, v in patch.items()}
        self._request("PATCH", url, json_body={"fields": fields})


class FirestoreError(RuntimeError):
    """A Firestore REST call failed (HTTP error / permission denied)."""
