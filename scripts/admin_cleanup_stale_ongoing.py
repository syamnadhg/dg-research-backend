"""One-off admin: mark every research with status="ongoing" or "paused" as
"stopped" for the user paired in research_config.json. Use after BE has
been wedged + restarted to clear stale Firestore state that wasn't
cleaned by the normal stop/pipeline-finally path.

Auth path matches the BE — user-scoped Firestore via the OS keystore
refresh token deposited by `cmd_pair_v2`. No service account needed.
"""
import json
import sys
import time
from pathlib import Path

# Make the BE's auth/ package importable when running from scripts/.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from auth import v2_flow, keystore as _ks  # noqa: E402

CFG_PATH = _REPO / "research_config.json"
cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
UID = cfg["pairedUid"]
DEVICE_ID = cfg["deviceId"]
print(f"Paired UID: {UID}")
print(f"Device:     {DEVICE_ID}")

install_uuid = _ks.install_uuid()
if _ks.try_recover(install_uuid) is None:
    print("ERROR: keystore empty — run `python research.py --pair` first")
    sys.exit(1)
db = v2_flow.init_firestore_user_scoped(install_uuid)
if db is None:
    print("ERROR: refresh token rejected — re-pair via Account → Add Device")
    sys.exit(1)
print("Firestore client OK")

# Query stuck statuses: ongoing + paused + running. "completed" and
# "stopped" are terminal and left alone.
researches = db.collection("users").document(UID).collection("researches")
STUCK = {"ongoing", "running", "paused"}
now_ms = int(time.time() * 1000)

to_stop = []
for doc in researches.stream():
    data = doc.to_dict() or {}
    status = (data.get("status") or "").lower()
    if status in STUCK:
        to_stop.append((doc.id, status, data.get("title") or data.get("topic") or "(no title)"))

if not to_stop:
    print("No stale ongoing/paused/running runs found.")
    sys.exit(0)

print(f"\nFound {len(to_stop)} stuck run(s):")
for rid, status, title in to_stop:
    print(f"  {rid:50s} {status:10s} {title[:60]}")

print("\nMarking all as 'stopped'...")
for rid, status, title in to_stop:
    try:
        researches.document(rid).update({
            "status": "stopped",
            "updatedAt": now_ms,
            "stoppedAt": now_ms,
            "stoppedBy": "admin_cleanup_stale_ongoing",
            "stoppedReason": f"admin cleanup — was stuck at {status}",
            "deviceId": DEVICE_ID,
        })
        print(f"  OK  {rid}")
    except Exception as e:
        print(f"  ERR {rid}: {e}")

print("\nDone.")
