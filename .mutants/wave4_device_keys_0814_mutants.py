"""Mutation harness for the backend half of the per-device key move (wave 4).

THE FINDING was on the web app's rules: a sharer's API keys were readable by
the device owner. Rules cannot restrict a read to some FIELDS of a document,
so the fix is the shape — one document per computer, which a machine may open
only when the path names its own deviceId claim. That makes this file's read
path load-bearing in two directions at once:

  • the SHARER's key must still arrive, because their run bills their key, and
  • their prefs document must NOT, because it holds their account-wide keys,
    their pair-code-lock hash and their delivery address, and the machine
    doing the reading belongs to somebody else.

⛔ The over-corrections are the dangerous half here. A device-key layer that
applies unconditionally (B4) lets a cleared override blank a working flat key.
A submitter read that fails CLOSED (B7) turns a mid-run unshare into a dead
owner chain rather than a graceful fallback. And dropping the legacy layer
(B8/B2) breaks every install whose owner has not signed in since the move —
the map is still their only copy until the web app's sweep reaches them.

Safety: refuses to start on a dirty tree, holds originals in memory only,
restores in `finally`, and re-checks `git status` at the end.

    .venv/bin/python .mutants/wave4_device_keys_0814_mutants.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = "research.py"

SUITES = "tests/test_device_scoped_keys_928.py tests/test_sharer_keys_938.py"

MUTANTS = [
    # ── the sharer read: what it must and must not reach ────────────────────
    ("B1", "under", "⭐⭐ the finding restored — the submitter's whole prefs doc read from a computer they do not own",
     [('        snap = _firebase_db.collection("users").document(submitter_uid) \\\n'
       '            .collection("deviceKeys").document(device_id).get()\n'
       '        keys = (snap.to_dict() or {}) if snap.exists else {}',
       '        snap = _firebase_db.collection("users").document(submitter_uid) \\\n'
       '            .collection("settings").document("prefs").get()\n'
       '        keys = ((snap.to_dict() or {}).get("apiKeys") or {}) if snap.exists else {}')]),
    ("B2", "under", "the sharer overlay loses its field allowlist — a stray field in their key doc shadows the owner's value",
     [("        for k in _SHARER_OVERRIDABLE_FIELDS:\n            v = submitter_keys.get(k)",
       "        for k in submitter_keys:\n            v = submitter_keys.get(k)")]),
    ("B3", "over", "⛔ the submitter read fails CLOSED — a mid-run unshare 403 takes the owner chain down with it instead of falling back",
     [('    except Exception as se:\n'
       '        log(f"[_read_firestore_api_keys] sharer key doc read failed (non-fatal, owner-chain fallback): {se}", "WARN")',
       '    except Exception as se:\n'
       '        raise se')]),
    ("B4", "under", "the 30s memo is gone — every ~6s narrator resolve re-reads the sharer's doc",
     [('    if (_SHARER_PREFS_CACHE["uid"] == submitter_uid\n'
       '            and now - _SHARER_PREFS_CACHE["ts"] < _SHARER_PREFS_TTL):',
       '    if (False\n'
       '            and now - _SHARER_PREFS_CACHE["ts"] < _SHARER_PREFS_TTL):')]),

    # ── the owner read: three layers, and the order between them ────────────
    ("B5", "under", "⭐ the per-device document is never read — the canonical home exists and nothing consults it",
     [("        device_doc = _read_device_key_doc(uid, did)", "        device_doc = {}")]),
    ("B6", "under", "the overlay ignores the document it was passed — same silence, one layer down",
     [("    if isinstance(device_doc, dict):\n"
       "        for k, v in device_doc.items():\n"
       "            if isinstance(v, str) and v.strip():\n"
       "                flat[k] = v.strip()\n",
       "")]),
    ("B7", "under", "⭐ the legacy map is applied ON TOP of the document — a freshly migrated key is shadowed by the stale copy it replaced",
     [("    by_device = (keys or {}).get(\"byDevice\")\n"
       "    if device_id and isinstance(by_device, dict):\n"
       "        dev = by_device.get(device_id)\n"
       "        if isinstance(dev, dict):\n"
       "            for k, v in dev.items():\n"
       "                if isinstance(v, str) and v.strip():\n"
       "                    flat[k] = v.strip()\n"
       "    if isinstance(device_doc, dict):\n"
       "        for k, v in device_doc.items():\n"
       "            if isinstance(v, str) and v.strip():\n"
       "                flat[k] = v.strip()\n",
       "    if isinstance(device_doc, dict):\n"
       "        for k, v in device_doc.items():\n"
       "            if isinstance(v, str) and v.strip():\n"
       "                flat[k] = v.strip()\n"
       "    by_device = (keys or {}).get(\"byDevice\")\n"
       "    if device_id and isinstance(by_device, dict):\n"
       "        dev = by_device.get(device_id)\n"
       "        if isinstance(dev, dict):\n"
       "            for k, v in dev.items():\n"
       "                if isinstance(v, str) and v.strip():\n"
       "                    flat[k] = v.strip()\n")]),
    ("B8", "over", "⛔ the legacy layer is dropped entirely — every install whose owner has not signed in since the move loses its key",
     [("    by_device = (keys or {}).get(\"byDevice\")\n"
       "    if device_id and isinstance(by_device, dict):\n"
       "        dev = by_device.get(device_id)\n"
       "        if isinstance(dev, dict):\n"
       "            for k, v in dev.items():\n"
       "                if isinstance(v, str) and v.strip():\n"
       "                    flat[k] = v.strip()\n",
       "")]),
    ("B9", "over", "⛔ a blank value in the document counts — a cleared override blanks the flat key it was supposed to revert to",
     [("        for k, v in device_doc.items():\n"
       "            if isinstance(v, str) and v.strip():\n"
       "                flat[k] = v.strip()",
       "        for k, v in device_doc.items():\n"
       "            flat[k] = str(v).strip()")]),
    ("B10", "under", "a missing prefs document ends the read again — an account whose only key is in the new document resolves nothing",
     [('        keys = {}\n'
       '        snap = _firebase_db.collection("users").document(uid) \\\n'
       '            .collection("settings").document("prefs").get()\n'
       '        if snap.exists:\n'
       '            keys = (snap.to_dict() or {}).get("apiKeys") or {}',
       '        snap = _firebase_db.collection("users").document(uid) \\\n'
       '            .collection("settings").document("prefs").get()\n'
       '        if not snap.exists:\n'
       '            return {}\n'
       '        keys = (snap.to_dict() or {}).get("apiKeys") or {}')]),
    ("B11", "over", "⛔ the device-key read fails closed — one Firestore blip on a separate document nukes the whole chain, flat keys included",
     [('    except Exception as e:\n'
       '        log(f"[_read_firestore_api_keys] device key doc read failed (non-fatal): {e}", "WARN")\n'
       '        return {}',
       '    except Exception as e:\n'
       '        raise e')]),
    ("B12", "under", "the read is not scoped by device — the path is what the rule checks, so this is the request a machine is refused",
     [('            .collection("deviceKeys").document(device_id).get()\n'
       '        return (snap.to_dict() or {}) if snap.exists else {}\n'
       '    except Exception as e:\n'
       '        log(f"[_read_firestore_api_keys] device key doc read failed',
       '            .collection("deviceKeys").document("shared").get()\n'
       '        return (snap.to_dict() or {}) if snap.exists else {}\n'
       '    except Exception as e:\n'
       '        log(f"[_read_firestore_api_keys] device key doc read failed')]),

    # ── observability ───────────────────────────────────────────────────────
    ("B13", "under", "the override log reads only the legacy map — it falls silent the moment a key migrates, and prints 'cleared' for one that works",
     [("            for src in (_dev_legacy, device_doc)", "            for src in (_dev_legacy,)")]),
]


def sh(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", "research.py", "tests"]).stdout
    return [ln for ln in out.splitlines() if ln and not ln.startswith("?? ")]


def run_tests() -> bool:
    return sh([sys.executable, "-m", "pytest", *SUITES.split(), "-q"]).returncode == 0


def main() -> int:
    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    path = ROOT / RESEARCH
    survivors = []
    for mid, direction, why, edits in MUTANTS:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                # ⛔⛔ UNIQUENESS, NOT MERE PRESENCE. `str.replace` takes the
                # FIRST match, and an anchor that also appears elsewhere
                # mutates a place the mutant was never about — silently
                # reporting a suite gap that does not exist while hiding the
                # one that does. A 2,300-line miss on this very file is why.
                if frm == to:
                    raise AssertionError(f"replacement is identical to the anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(f"anchor occurs {hits}x (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            path.write_text(mutated, encoding="utf-8")
            killed = not run_tests()
            print(f"{'✓ killed  ' if killed else '✗ SURVIVED'} {mid} [{direction}] {why}")
            if not killed:
                survivors.append((mid, direction, why, False))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            survivors.append((mid, direction, why, True))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in MUTANTS if m[1] == "over")
    print(f"\n{len(MUTANTS) - len(survivors)}/{len(MUTANTS)} killed ({over} over-corrections)")
    broken = [m for m in survivors if m[3]]
    real = [m for m in survivors if not m[3]]
    if broken:
        print("⚠ STALE ANCHORS (harness faults — these measured NOTHING, fix and re-run):\n"
              + "\n".join(f"  {m} {w}" for m, _d, w, _b in broken))
    if real:
        print("SURVIVORS (real suite gaps):\n"
              + "\n".join(f"  {m} [{d}] {w}" for m, d, w, _b in real))
    if survivors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
