"""One-off diagnostic: dump the paired user's recent push_audit docs.

Reads users/{paired_uid}/push_audit/* and prints the per-notification
decision trail so we can tell whether a missing push is:
  (a) /api/notify never being called by the FE (sendNotification skipped)
  (b) Called, but channels stripped (per-event pref / master gate)
  (c) Push allowed but FCM send failed / zero registered tokens

Also dumps users/{paired_uid}/settings/prefs to surface the per-event
channel prefs + dataControls.pushEnabled master flag in one place.

Usage:
    python scripts/dump_push_audit.py            # default: last 20 audits
    python scripts/dump_push_audit.py --limit 50
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Make research.py importable for its Firebase init helpers
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import research  # noqa: E402  (initializes Firebase Admin on import setup)


def _trunc(s, n=80):
    s = str(s)
    return s if len(s) <= n else s[:n] + "…"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20, help="how many recent audit docs to dump")
    args = ap.parse_args()

    if not research.init_firebase():
        print("[ERROR] Firebase init failed — check firebase-service-account.json")
        sys.exit(1)

    uid = research.load_paired_uid()
    if not uid:
        print("[ERROR] No paired uid — run `python research.py --pair` first")
        sys.exit(1)
    print(f"[info] paired uid: {uid[:8]}…\n")

    db = research._firebase_db

    # ── User settings (prefs + master push toggle) ─────────────────
    prefs_snap = db.collection("users").document(uid) \
        .collection("settings").document("prefs").get()
    prefs = prefs_snap.to_dict() if prefs_snap.exists else {}
    print("═════ user settings ═════")
    print(f"  dataControls.pushEnabled: {prefs.get('dataControls', {}).get('pushEnabled')}")
    notif_prefs = prefs.get("notifications", {}) or {}
    if notif_prefs:
        print(f"  notifications (per-event channel prefs):")
        for evt_type, val in sorted(notif_prefs.items()):
            print(f"    {evt_type:<28} {val}")
    else:
        print(f"  notifications: <empty — defaults will apply>")
    api_keys = prefs.get("apiKeys", {}) or {}
    if api_keys:
        print(f"  apiKeys present: {sorted(api_keys.keys())}")
    print()

    # ── FCM token inventory ───────────────────────────────────────
    tokens_snap = db.collection("users").document(uid) \
        .collection("fcm_tokens").get()
    tokens = list(tokens_snap)
    print(f"═════ FCM tokens ═════")
    print(f"  total registered: {len(tokens)}")
    for i, doc in enumerate(tokens, 1):
        data = doc.to_dict() or {}
        # Doc ID is the full FCM token; truncate to last 12 for safety
        tail = doc.id[-12:] if doc.id else "?"
        ua = data.get("userAgent", "")
        last = data.get("lastUsedAt") or data.get("createdAt")
        print(f"    [{i}] …{tail}  ua={_trunc(ua, 60)}  last={last}")
    print()

    # ── Recent push_audit docs ────────────────────────────────────
    audits_ref = db.collection("users").document(uid).collection("push_audit")
    audits = list(audits_ref.order_by("ts", direction="DESCENDING").limit(args.limit).stream())
    print(f"═════ push_audit (last {len(audits)}) ═════")
    if not audits:
        print("  <no audit docs — /api/notify was never called for this uid since the audit shipped>")
    for i, doc in enumerate(audits, 1):
        data = doc.to_dict() or {}
        ts = data.get("ts")
        ts_str = ""
        if ts:
            from datetime import datetime, timezone
            ts_str = datetime.fromtimestamp(ts / 1000, timezone.utc).isoformat(timespec="seconds")
        ch = data.get("channelsDecided") or {}
        results = data.get("results") or []
        ok_count = sum(1 for r in results if r.get("ok"))
        err_codes = sorted({r.get("code") for r in results if r.get("code")})
        print(f"  [{i}] {ts_str}  type={data.get('type')}")
        print(f"      pushEnabled(master)={data.get('pushEnabled')}  channelsDecided={ch}")
        print(f"      tokenCount={data.get('tokenCount')}  pushed={data.get('pushed')}  ok={ok_count}/{len(results)}")
        if err_codes:
            print(f"      err_codes={err_codes}")
            for r in results:
                if not r.get("ok"):
                    msg = _trunc(r.get("errorMsg") or "", 100)
                    print(f"        ✗ …{r.get('token')}  code={r.get('code')}  {msg}")
        print()


if __name__ == "__main__":
    main()
