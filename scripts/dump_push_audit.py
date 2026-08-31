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
        # ⛔ THE OLD MESSAGE NAMED A FILE THAT DOES NOT EXIST. It said "check
        # firebase-service-account.json", and `init_firebase`'s own docstring
        # says the opposite in as many words: "No Admin SDK; no
        # firebase-service-account.json on disk." It is backed by the
        # OS-keystore refresh token, so the only recovery is re-pairing.
        print("[ERROR] Firestore init failed — this reads Firestore as the PAIRED USER "
              "(OS-keystore refresh token, no service account). Run "
              "`superresearch --pair` if the keystore is empty or the token was revoked.")
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
        print("  notifications (per-event channel prefs):")
        for evt_type, val in sorted(notif_prefs.items()):
            print(f"    {evt_type:<28} {val}")
    else:
        print("  notifications: <empty — defaults will apply>")
    api_keys = prefs.get("apiKeys", {}) or {}
    if api_keys:
        print(f"  apiKeys present: {sorted(api_keys.keys())}")
    print()

    # ── FCM token inventory ───────────────────────────────────────
    tokens_snap = db.collection("users").document(uid) \
        .collection("fcm_tokens").get()
    tokens = list(tokens_snap)
    print("═════ FCM tokens ═════")
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
    # ⛔⛔ THIS READ RAISED PermissionDenied FROM THE DAY THE SCRIPT WAS WRITTEN
    # UNTIL 2026-08-31, and nothing here said so. `push_audit` had no match
    # block in firestore.rules — its three siblings (notifications, fcm_tokens,
    # notify_dedup) all did — so the deny-all catch-all caught it, and this
    # script reads as the PAIRED USER, not the Admin SDK. The collection was
    # written by the server every delivery and readable by nothing on the
    # machine that needed it. The rule exists now; the guard stays, because a
    # diagnostic that dies on its own last section after printing two useful
    # ones should say which section died and why.
    try:
        audits = list(audits_ref.order_by("ts", direction="DESCENDING")
                      .limit(args.limit).stream())
    except Exception as e:  # noqa: BLE001 — a diagnostic must not end on a traceback
        print(f"═════ push_audit ═════\n  [ERROR] could not read the audit trail: "
              f"{type(e).__name__}: {e}")
        print("  If this is PermissionDenied, this deployment's firestore.rules "
              "predates the `push_audit` match block — deploy the rules.")
        return
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
        # ⭐ ADDED 2026-08-31 WITH ITS WRITER. Three dedup verdicts and a
        # transaction fault all clear push and email, which is byte-identical
        # to a category the person muted — so `channelsDecided` alone cannot
        # tell a suppression WE chose from a switch THEY turned off.
        dedup = data.get("dedupSuppressed")
        dedup_str = f"  dedupSuppressed={dedup}" if dedup else ""
        print(f"      pushEnabled(master)={data.get('pushEnabled')}  "
              f"channelsDecided={ch}{dedup_str}")
        # ⛔ `staleCulled` WAS WRITE-ONLY. notify-deliver has persisted it since
        # the token-culling work, and the only reader of this collection never
        # printed it — so a fan-out that shrank because tokens were culled as
        # stale looked identical to a user who quietly stopped registering
        # devices. That distinction is the whole reason the field is written.
        culled = data.get("staleCulled")
        culled_str = f"  staleCulled={culled}" if culled else ""
        print(f"      tokenCount={data.get('tokenCount')}{culled_str}  "
              f"pushed={data.get('pushed')}  ok={ok_count}/{len(results)}")
        if err_codes:
            print(f"      err_codes={err_codes}")
            for r in results:
                if not r.get("ok"):
                    msg = _trunc(r.get("errorMsg") or "", 100)
                    print(f"        ✗ …{r.get('token')}  code={r.get('code')}  {msg}")
        print()


if __name__ == "__main__":
    main()
