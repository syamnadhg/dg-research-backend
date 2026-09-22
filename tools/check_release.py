#!/usr/bin/env python3
"""Refuse a release whose wheels were not all built from the same source.

WHY
---
The wheels of one release are built on different machines (the Mac here; the
Windows box, and WSL on it, for the others) and must publish together — see
"Every platform wheel of a release publishes together" in ARCHITECTURE.md. Until
wave 10.9 nothing could say whether they held the same code: a compiled module
cannot be read back to its source, and a wheel carried no record of where it
came from.

tools/build_compiled.py now writes `_sr_build.json` into the tree before it
compiles anything (`stamp_tree`): `source_sha256`, a fingerprint of the
first-party .py sources with CRLF read as LF, so the same code gives the same
value whether the build tree came from git, rsync or a zip, on any OS; plus
`commit` and `dirty` where git could answer. This reads that stamp back out of
every wheel it is given, prints them side by side, and exits 1 if any wheel has
no readable stamp or the fingerprints disagree. `commit` and `dirty` are shown,
never compared: two machines can build the same source from different commits.

Run it on the staged release, right before the single publish command.

USAGE
-----
    python tools/check_release.py dist/*.whl
    python tools/check_release.py <staging-dir>      # every *.whl in it
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

#: Must equal `STAMP_NAME` in tools/build_compiled.py. Kept as its own literal so
#: this stays a standalone script; tests/test_release_provenance.py stamps a
#: tree with the build's function and reads it back with this one, which is the
#: check that the two names agree.
STAMP_NAME = "_sr_build.json"


def read_stamp(wheel: Path) -> "dict | None":
    """The provenance stamp inside `wheel`, or None when there is no usable one:
    not a zip, no stamp, not JSON, or no `source_sha256` in it."""
    try:
        with zipfile.ZipFile(wheel) as z:
            stamp = json.loads(z.read(STAMP_NAME).decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None
    if not isinstance(stamp, dict) or not stamp.get("source_sha256"):
        return None
    return stamp


def check(wheels: "list[Path]") -> "tuple[bool, list[str]]":
    """(ok, report lines) for one release's wheels."""
    if not wheels:
        return False, ["REFUSED: no wheels given — checking nothing is not a pass"]
    lines: "list[str]" = []
    problems: "list[str]" = []
    sources: "set[str]" = set()
    for wheel in wheels:
        stamp = read_stamp(wheel)
        if stamp is None:
            lines.append(f"  {wheel.name}\n      no readable {STAMP_NAME}")
            problems.append(f"{wheel.name} carries no provenance stamp — built before "
                            "stamps existed, or not by tools/build_compiled.py")
            continue
        sources.add(stamp["source_sha256"])
        lines.append(f"  {wheel.name}\n      source_sha256={stamp['source_sha256']}  "
                     f"commit={stamp.get('commit') or 'unknown'}  dirty={stamp.get('dirty')}")
    if len(sources) > 1:
        problems.append(f"the wheels fingerprint {len(sources)} different sources — "
                        "they were not built from the same code")
    if problems:
        return False, lines + ["REFUSED: " + p for p in problems]
    return True, lines + [f"OK: every wheel ({len(wheels)}) was built from the same source"]


def wheels_from(args: "list[str]") -> "list[Path]":
    """The wheels named on the command line; a directory stands for its *.whl."""
    out: "list[Path]" = []
    for arg in args:
        p = Path(arg)
        out.extend(sorted(p.glob("*.whl")) if p.is_dir() else [p])
    return out


def main(argv: "list[str] | None" = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    ok, lines = check(wheels_from(args))
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
