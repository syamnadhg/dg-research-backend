"""Find the support bundle a quoted code names, on this machine.

⛔⛔ WHY THIS EXISTS. A support code is Crockford base32, which drops the letters
O, I and L precisely so a code read aloud cannot come back as a different one —
and nothing anywhere performed the substitution that makes that true. Measured
2026-08-22: the owner read `1Z0FGVED` back as `1ZOFGVED`, and because `O` is not
in the alphabet the code as typed exists nowhere. Dropping the letter bought a
hard refusal instead of a recovery.

`--send-logs` leaves every archive it builds in `~/.super-research/logs/outgoing/`
under the code's own name, so the machine that sent one can still produce it from
the code alone.

Usage:
    python scripts/find_support_bundle.py 1ZOFGVED
    python scripts/find_support_bundle.py "1zof-gved"     # separators and case
    python scripts/find_support_bundle.py --list
"""
import argparse
import sys
from pathlib import Path

# Make research.py importable for the normaliser and the log root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import research  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("code", nargs="?", default="",
                    help="the support code as it was quoted to you")
    ap.add_argument("--list", action="store_true", dest="list_all",
                    help="just list the bundles this machine still has")
    args = ap.parse_args()

    if not args.code and not args.list_all:
        ap.error("give a code, or --list")

    found = research.find_local_support_bundle(args.code)
    print(f"searched  {found['searched']}")

    if args.list_all or not args.code:
        if not found["available"]:
            print("no bundles on this machine")
            return 1
        for code in found["available"]:
            print(f"  {code}")
        return 0

    if not found["code"]:
        print(f"{args.code!r} is not a support code even after normalising "
              f"(8 characters of Crockford base32)")
        return 2

    if found["code"] != args.code.upper():
        # ⭐ Say what was changed and why, rather than silently resolving
        # something the person did not type — they may be holding a different
        # code entirely. The letter rule is named only when a letter was really
        # substituted; case and dashes are not that.
        why = (f"   ({', '.join(found['remapped'])}: the alphabet has none of "
               f"these letters)" if found["remapped"] else "")
        print(f"read as    {found['code']}{why}")

    if found["path"]:
        print(f"found      {found['path']}  ({found['sizeBytes']} bytes)")
        return 0

    print(f"not here   no bundle for {found['code']} on this machine")
    if found["available"]:
        print("this machine has: " + ", ".join(found["available"]))
    return 1


if __name__ == "__main__":
    sys.exit(main())
