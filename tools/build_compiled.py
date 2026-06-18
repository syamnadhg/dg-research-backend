#!/usr/bin/env python3
"""Build a source-hidden (Nuitka-compiled) platform wheel for Super Research.

WHY
---
`pipx install superresearch` gives anyone the install UX, but a plain wheel ships
readable .py. This produces an equivalent wheel where our first-party code is
compiled to native extensions (Nuitka), so the source isn't shipped — while the
install + every runtime behavior stay identical to the source wheel.

PIPELINE
--------
1. Build the normal source wheel (`pip wheel . --no-deps`) — gives us correct
   METADATA / entry_points / dist-info for free.
2. Unpack it.
3. Compile each first-party top-level module to a native extension via
   `nuitka --module`, and DELETE its source .py from the unpacked tree:
       research.py  ->  _sr_core.<abi>.pyd     (RENAMED — so a readable
                                                research.py launcher shim can
                                                coexist; see SHIM below)
       models/prompts/vision/narrate.py -> <name>.<abi>.pyd
   research.py is replaced by a tiny readable launcher shim that re-exports
   `main` from _sr_core (keeps `superresearch` = research:main, `python
   research.py …`, and the windowless pythonw supervisor re-exec all working —
   a .pyd can't be executed as a script and needs a stable import name).
4. Repack (regenerates RECORD) and retag the wheel platform + python-minor
   specific (cp<ver>-cp<ver>-<platform>).

SCOPE (v1): the 5 top-level modules are compiled (the 2.1 MB core + the prompt
IP). auth/ (small pairing/keystore plumbing against documented Firebase
endpoints) and scripts/ stay as source for now — compiling package submodules
has a PyInit symbol-name subtlety to validate first. Set --compile-auth to
opt in once that's verified.

USAGE
-----
    python tools/build_compiled.py [--outdir dist] [--keep-build] [--compile-auth]

REQUIRES: nuitka, wheel, and a C compiler (MSVC on Windows / gcc|clang on POSIX).
The resulting wheel is python-minor + platform specific (e.g.
cp314-cp314-win_amd64) — build it on EACH OS/python you want to publish for.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent  # tools/ -> repo root

# First-party top-level modules to compile. research.py is special (renamed to
# _sr_core so the readable launcher shim can keep the `research` name).
TOP_MODULES = ["models", "prompts", "vision", "narrate"]
AUTH_SUBMODULES = ["v2_flow", "keystore", "credentials", "pairing"]

SHIM = '''#!/usr/bin/env python3
"""Launcher shim for the COMPILED Super Research build.

The pipeline is compiled into _sr_core.<abi>.pyd (Nuitka). This readable stub is
the only first-party top-level source file in the wheel; it exists so the
`superresearch` console entry (research:main), `python research.py ...`, and the
windowless pythonw supervisor re-exec all keep working (a .pyd can't be run as a
script and needs a stable importable name). It just hands off to main()."""
import sys
from _sr_core import main  # re-exported so `research:main` resolves to the core
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\\n  Cancelled. Re-run when ready.")
        sys.exit(130)
'''


def run(cmd: list, **kw) -> None:
    print("  $", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, **kw)


def nuitka_module(src_py: Path, out_dir: Path) -> None:
    """Compile one .py to a native extension into out_dir (flat). --remove-output
    drops the multi-100MB .build/ C-source dir, keeping only the .pyd/.so."""
    run([sys.executable, "-m", "nuitka", "--module", str(src_py),
         f"--output-dir={out_dir}", "--assume-yes-for-downloads", "--remove-output"])


def find_artifact(out_dir: Path, stem: str) -> Path:
    for pat in (f"{stem}.*.pyd", f"{stem}.*.so", f"{stem}.pyd", f"{stem}.so"):
        hits = sorted(out_dir.glob(pat))
        if hits:
            return hits[0]
    raise SystemExit(f"compiled artifact for '{stem}' not found in {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the Nuitka-compiled Super Research wheel.")
    ap.add_argument("--outdir", default="dist", help="where to drop the final wheel (default: dist/)")
    ap.add_argument("--keep-build", action="store_true", help="keep the temp work dir for inspection")
    ap.add_argument("--compile-auth", action="store_true",
                    help="also compile auth/ submodules (experimental — verify PyInit resolution)")
    args = ap.parse_args()

    outdir = (REPO / args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="sr_compiled_"))
    comp = work / "compiled"
    comp.mkdir()
    print(f"[build] repo={REPO}")
    print(f"[build] work={work}")

    # 1. source wheel (for metadata / entry_points / dist-info)
    (work / "src").mkdir()
    print("[build] building source wheel …")
    run([sys.executable, "-m", "pip", "wheel", str(REPO), "--no-deps", "-w", str(work / "src")])
    src_whl = next((work / "src").glob("superresearch-*.whl"))

    # 2. unpack
    run([sys.executable, "-m", "wheel", "unpack", str(src_whl), "-d", str(work / "unpacked")])
    tree = next((work / "unpacked").glob("superresearch-*"))
    print(f"[build] tree={tree}")

    # 3a. research.py -> _sr_core.<abi>.pyd, then replace research.py with the shim
    core_src = comp / "_sr_core.py"
    shutil.copy(tree / "research.py", core_src)
    print("[build] compiling research.py -> _sr_core (the 2.1MB core — slow, ~5-6 min) …")
    nuitka_module(core_src, comp)
    core_pyd = find_artifact(comp, "_sr_core")
    shutil.copy(core_pyd, tree / core_pyd.name)
    (tree / "research.py").unlink()
    (tree / "research.py").write_text(SHIM, encoding="utf-8")
    print(f"[build]   -> {core_pyd.name} + readable research.py launcher shim")

    # 3b. top-level siblings
    for m in TOP_MODULES:
        print(f"[build] compiling {m}.py …")
        nuitka_module(tree / f"{m}.py", comp)
        pyd = find_artifact(comp, m)
        shutil.copy(pyd, tree / pyd.name)
        (tree / f"{m}.py").unlink()
        print(f"[build]   -> {pyd.name}")

    # 3c. auth submodules (opt-in; auth/__init__.py stays readable either way)
    if args.compile_auth:
        for m in AUTH_SUBMODULES:
            print(f"[build] compiling auth/{m}.py …")
            nuitka_module(tree / "auth" / f"{m}.py", comp)
            pyd = find_artifact(comp, m)
            shutil.copy(pyd, tree / "auth" / pyd.name)
            (tree / "auth" / f"{m}.py").unlink()
            print(f"[build]   -> auth/{pyd.name}")
    else:
        print("[build] auth/ left as source (pass --compile-auth to compile it)")

    # 4. repack + retag platform-specific
    (work / "packed").mkdir()
    run([sys.executable, "-m", "wheel", "pack", str(tree), "-d", str(work / "packed")])
    raw = next((work / "packed").glob("*.whl"))
    pyver = f"cp{sys.version_info.major}{sys.version_info.minor}"
    plat = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    run([sys.executable, "-m", "wheel", "tags",
         "--python-tag", pyver, "--abi-tag", pyver, "--platform-tag", plat,
         "--remove", str(raw)])
    final = next((work / "packed").glob("*.whl"))
    dest = outdir / final.name
    shutil.copy(final, dest)

    print(f"\n[build] DONE -> {dest}")
    print(f"[build] tag: {pyver}-{pyver}-{plat}  (python-minor + platform specific)")
    if not args.keep_build:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"[build] kept work dir: {work}")


if __name__ == "__main__":
    main()
