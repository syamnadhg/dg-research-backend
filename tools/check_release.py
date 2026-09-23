#!/usr/bin/env python3
"""Refuse a release that is not all of one release: a platform's wheel missing, or
wheels that were not all built from the same source.

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

⛔⛔ AND IT COUNTS THE PLATFORMS (repair round 2). Agreeing about the source says
nothing about whether the release is WHOLE, and one wheel agrees with itself:
staged without the Mac wheel — the one carried over to the Windows box by hand —
this printed "OK: every wheel (1) was built from the same source" and exited 0,
the one gate that exists to stop exactly that. A version on PyPI without one
platform's wheel takes every host on that platform down at its next upgrade, so a
missing platform is refused here and named.

Run it on the staged release, right before the single publish command.

The agent's own wheel (`superresearch_agent-*`) may sit in the same folder: it is
named, set aside with a line saying so, and never counted as a machine wheel.

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

#: The platforms one release publishes together, each keyed by the fragment the
#: build writes into the wheel's platform tag and named the way a person says it.
#: ⛔ A FRAGMENT, NOT A WHOLE TAG: the Mac wheel's tag carries its deployment
#: target (`macosx_11_0_arm64`, `macosx_14_0_arm64` — tools/build_compiled.py
#: `--macos-target`) and the manylinux tag its glibc, so a release would fail this
#: check the day either moved. What must be true is that each platform is HERE.
REQUIRED_PLATFORMS = {"macosx": "macOS", "win_amd64": "Windows", "manylinux": "Linux"}

#: The agent's distribution, as a wheel file name spells it.
#: ⛔⛔ SKIPPED, AND SAID SO, RATHER THAN REFUSED (2026-09-23). Staged in the same
#: folder as the three machine wheels, the agent wheel was refused as "carries no
#: provenance stamp" and the whole release with it — so the only way to pass was
#: to publish the two packages from two folders, which the checklist never said.
#: ⭐ It is not part of what this checks, and accepting it would mean nothing: it
#: is a separate package with its own version, it is pure Python, and it is
#: built ONCE for every platform, so there is no second machine whose build it
#: could disagree with. Its own checks are `tools/bump_version.py --check` before
#: the publish and `--post-publish` (which asks PyPI) after it.
#: ⛔ Matched by NAME, never by the `py3-none-any` tag: that tag is also what the
#: machine build's source-mode fallback writes, and that wheel must still count
#: as no platform at all.
AGENT_DISTRIBUTION = "superresearch_agent"


def distribution(wheel: Path) -> str:
    """The distribution `wheel`'s file name declares: its first "-" field, which
    a wheel name always spells with "_" for the project's own "-"."""
    return wheel.name.split("-", 1)[0]


def platform_tag(wheel: Path) -> str:
    """The platform tag `wheel`'s file name declares — the last of the "-" fields
    of a wheel name — or "" when the name is not a wheel's at all. The build's
    source-mode fallback tags `py3-none-any`, which is no platform."""
    if wheel.suffix != ".whl":
        return ""
    return wheel.stem.rpartition("-")[2]


def missing_platforms(wheels: "list[Path]") -> "list[str]":
    """The platforms of `REQUIRED_PLATFORMS` no wheel here carries, in that order."""
    tags = [platform_tag(w) for w in wheels]
    return [name for key, name in REQUIRED_PLATFORMS.items()
            if not any(key in tag for tag in tags)]


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
    """(ok, report lines) for one release's wheels: every `REQUIRED_PLATFORMS`
    platform present, every wheel stamped, and one source behind them all. An
    agent wheel among them is named and set aside (see `AGENT_DISTRIBUTION`)."""
    agent = [w for w in wheels if distribution(w) == AGENT_DISTRIBUTION]
    skipped = [f"  {w.name}\n      skipped - the agent is its own package, checked by "
               "tools/bump_version.py --check before the publish and --post-publish "
               "after it" for w in agent]
    wheels = [w for w in wheels if w not in agent]
    if not wheels:
        return False, [*skipped, "REFUSED: no machine wheels given — checking nothing "
                                 "is not a pass"]
    lines: "list[str]" = [*skipped]
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
    absent = missing_platforms(wheels)
    if absent:
        problems.append("this is not a whole release — no " + " and no ".join(absent)
                        + " wheel. Publishing a version without one platform's wheel "
                        "takes every host on that platform down at its next upgrade.")
    if problems:
        return False, lines + ["REFUSED: " + p for p in problems]
    return True, lines + [f"OK: every wheel ({len(wheels)}) was built from the same "
                          f"source, and all {len(REQUIRED_PLATFORMS)} platforms are here"]


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
