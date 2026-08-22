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
       models/prompts/vision/narrate/selfheal.py -> <name>.<abi>.pyd
   research.py is replaced by a tiny readable launcher shim that re-exports
   `main` from _sr_core (keeps `superresearch` = research:main, `python
   research.py …`, and the windowless pythonw supervisor re-exec all working —
   a .pyd can't be executed as a script and needs a stable import name).
4. Repack (regenerates RECORD) and retag the wheel platform + python-minor
   specific (cp<ver>-cp<ver>-<platform>).

SCOPE: every first-party top-level module is compiled (the pipeline core, the prompt
IP, and the self-heal machinery) — i.e. all of `py-modules` in pyproject.toml.
auth/ (small pairing/keystore plumbing against documented Firebase endpoints) and
scripts/ stay as source deliberately — compiling package submodules has a PyInit
symbol-name subtlety to validate first. Set --compile-auth to opt in once that's
verified.

Do NOT put a module count or a file size in prose anywhere in this file. Both drifted
once already — the scope note kept counting the modules after a sixth was added and
left uncompiled, and the compile banner kept quoting a core size the file had long
outgrown. Numbers in comments have no authority behind them and nothing re-checks
them. TOP_MODULES below is the only authority for what is compiled, the core's size
is measured at build time, and tests/test_compiled_wheel_covers_every_module.py
fails if either kind of number reappears here (including in a comment explaining
this rule — it matches patterns, not intent).

USAGE
-----
    python tools/build_compiled.py [--outdir dist] [--keep-build] [--compile-auth]

REQUIRES: nuitka, wheel, and a C compiler (MSVC on Windows / gcc|clang on POSIX).
The resulting wheel is python-minor + platform specific (e.g.
cp314-cp314-win_amd64) — build it on EACH OS/python you want to publish for.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent  # tools/ -> repo root

# First-party top-level modules to compile. research.py is special (renamed to
# _sr_core so the readable launcher shim can keep the `research` name).
#
# This list must stay in step with `[tool.setuptools] py-modules` in
# pyproject.toml — anything listed there and NOT here is packed into the wheel as
# readable source. `selfheal` was exactly that: it was added to py-modules on
# 2026-06-22, four days after this script was written, and shipped in the clear in
# every wheel from then until 0.1.12 because nobody came back to this line.
# tests/test_compiled_wheel_covers_every_module.py now fails if the two drift.
TOP_MODULES = ["models", "prompts", "vision", "narrate", "selfheal",
               "telemetry", "logquiet"]
AUTH_SUBMODULES = ["v2_flow", "keystore", "credentials", "pairing"]

# Admin/diagnostic scripts that sit in scripts/ but must NEVER ship in a wheel.
#
# The original rationale here said these were untracked, so the drop existed only to
# stop a working-tree build (Win/Linux) from differing cosmetically against a clean
# clone (Mac). That stopped being true on 2026-07-08, when both files were committed
# under an unrelated change — nothing re-checked the claim, so the comment quietly
# decayed into misdirection.
#
# What is actually true now: pyproject declares `packages = ["scripts"]`, so EVERY
# .py added to scripts/ is packed into the wheel automatically, and this hardcoded
# tuple is the ONLY thing keeping these two out. Add a new admin script to scripts/
# and it ships, readable, unless you also add it here.
#
# ⭐ 2026-08-14 — `claude_popover_capture.py` joined them, and for a reason worth
# stating: it is not merely useless in a wheel, it is BROKEN there. It does
# `import research` and then reaches for `research.p2_family` / `research.Browser`
# / `research.PROFILE_DIR`, and in the wheel `research` is the SHIM below, which
# exports `main` and nothing else. Same root cause as the vision/narrate key
# lookups fixed on 2026-08-13; this instance shipped in every wheel, failing with
# an AttributeError the moment anyone ran it. A source-tree diagnostic has no
# business in a user's install either way.
DROP_FROM_WHEEL = ("scripts/dump_push_audit.py", "scripts/admin_cleanup_stale_ongoing.py",
                   "scripts/claude_popover_capture.py",
                   # Support-side diagnostic: resolves a quoted support code to
                   # the bundle on this machine. `import research` reaches the
                   # SHIM in a wheel, so like its three siblings it is a
                   # source-tree tool only.
                   "scripts/find_support_bundle.py")

SHIM = '''#!/usr/bin/env python3
"""Launcher shim for the COMPILED Super Research build.

The pipeline is compiled into _sr_core.<abi>.pyd (Nuitka). This readable stub is
the only first-party top-level source file in the wheel; it exists so the
`superresearch` console entry (research:main), `python research.py ...`, and the
windowless pythonw supervisor re-exec all keep working (a .pyd can't be run as a
script and needs a stable importable name).

The heavy `_sr_core` import is LAZY (inside main()), so `--version` is INSTANT
instead of paying the ~3s native-extension import that every other command needs.
`main` stays the module attribute the console entry (research:main) resolves to."""
import sys


def main():
    # Fast path: print version (+ cached upgrade nudge) WITHOUT importing the
    # heavy compiled core. Keeps `--version` snappy; the nudge is read from the
    # 24h cache other commands populate (no network here).
    if "--version" in sys.argv:
        try:
            from importlib.metadata import version as _v
            cur = _v("superresearch")
        except Exception:
            cur = "?"
        print("  Super Research  v" + cur)
        try:
            import json, os
            _cache = os.path.join(os.path.expanduser("~"), ".super-research", ".version_check.json")
            latest = (json.load(open(_cache)).get("latest") or "") if os.path.exists(_cache) else ""
            def _gt(a, b):
                def _p(v): return [int("".join(c for c in s if c.isdigit()) or 0) for s in str(v).split(".")]
                return _p(a) > _p(b)
            if latest and cur != "?" and _gt(latest, cur):
                print("  \\u2191  v" + latest + " available \\u2014 run: superresearch --update")
        except Exception:
            pass
        return 0
    from _sr_core import main as _core_main  # lazy: only pay the import when needed
    return _core_main()


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
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
    ap.add_argument("--macos-target", default="11.0",
                    help="macOS deployment target for the wheel's platform tag (default: 11.0 = "
                         "Big Sur). WITHOUT this, building on a new macOS tags the wheel "
                         "macosx_<that version>_arm64 and it WON'T install on older Macs.")
    ap.add_argument("--also-source", action="store_true",
                    help="ALSO emit the universal py3-none-any SOURCE-fallback wheel (installs "
                         "on any Python 3.11+/OS — un-hidden source). Build it ONCE on any one "
                         "platform; it's platform-independent.")
    args = ap.parse_args()

    # On macOS, pin the deployment target BEFORE compiling so both the Nuitka/clang
    # build AND sysconfig.get_platform() (which sets the wheel's platform tag) use it.
    # Otherwise the tag inherits the build machine's macOS (e.g. macosx_26_0), which
    # pip refuses to install on any older Mac. 11.0 back-deploys broadly.
    if sys.platform == "darwin" and not os.environ.get("MACOSX_DEPLOYMENT_TARGET"):
        os.environ["MACOSX_DEPLOYMENT_TARGET"] = args.macos_target
        print(f"[build] MACOSX_DEPLOYMENT_TARGET={args.macos_target} (broad-compat tag)")
    if sys.platform == "darwin":
        # FAIL-LOUD tag guard (2026-07-19 incident): CPython IGNORES an env
        # MACOSX_DEPLOYMENT_TARGET LOWER than the interpreter's own build-time
        # target. On a Homebrew python (bottles target the bottle's macOS, e.g.
        # 26) the env pin above is silently ineffective and the wheel tags
        # macosx_26_0_arm64 — installable nowhere older. Check the DERIVED
        # platform up front, before the ~5-minute compile, and stop with the
        # remedy instead of emitting a mistagged wheel.
        derived = sysconfig.get_platform()
        want_prefix = f"macosx-{args.macos_target}-"
        if not derived.startswith(want_prefix):
            sys.exit(
                f"[build] ABORT: this interpreter derives platform '{derived}', not "
                f"'{want_prefix}*'. Its own build-time MACOSX_DEPLOYMENT_TARGET "
                f"({sysconfig.get_config_var('MACOSX_DEPLOYMENT_TARGET')}) is higher "
                f"than the requested {args.macos_target}, and CPython ignores a lower "
                "env override — the wheel would be mistagged for this macOS only. "
                "Build with a CPython whose own build target <= the requested one: "
                "the uv-managed 3.13 (`uv python install 3.13`; python-build-standalone "
                "targets 11.0 on arm64) or the python.org installer — never Homebrew."
            )

    outdir = (REPO / args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="sr_compiled_"))
    comp = work / "compiled"
    comp.mkdir()
    print(f"[build] repo={REPO}")
    print(f"[build] work={work}")

    # 1. source wheel (for metadata / entry_points / dist-info)
    #
    # Clear ./build first. `pip wheel <REPO>` drives setuptools IN-TREE, and
    # setuptools' build_py copies declared modules into ./build/lib but NEVER prunes
    # entries that are no longer declared — bdist_wheel then packs that whole
    # directory. So a module renamed or dropped from py-modules keeps shipping, as
    # readable source, from a stale copy that no longer has an on-disk counterpart.
    # Nothing downstream can catch it: the wheel builds, installs and imports under
    # the retired name, and the compile step never sees the file because it is not in
    # TOP_MODULES. Deleting the directory costs one rebuild of files we are about to
    # recompile anyway.
    stale_build = REPO / "build"
    if stale_build.exists():
        print(f"[build] clearing stale {stale_build} (setuptools never prunes it)")
        shutil.rmtree(stale_build, ignore_errors=True)

    (work / "src").mkdir()
    print("[build] building source wheel …")
    run([sys.executable, "-m", "pip", "wheel", str(REPO), "--no-deps", "-w", str(work / "src")])
    src_whl = next((work / "src").glob("superresearch-*.whl"))

    # 2. unpack
    run([sys.executable, "-m", "wheel", "unpack", str(src_whl), "-d", str(work / "unpacked")])
    tree = next((work / "unpacked").glob("superresearch-*"))
    print(f"[build] tree={tree}")

    # 2a. Drop local-only admin scripts so EVERY wheel is byte-consistent — a
    # working-tree build (Win/Linux) must match a clean-clone build (Mac) exactly.
    for rel in DROP_FROM_WHEEL:
        f = tree / rel
        if f.exists():
            f.unlink()
            print(f"[build] dropped local-only {rel}")

    # 2b. Optional py3-none-any SOURCE fallback — pack the CLEANED tree BEFORE
    # compiling (pure readable source, universal). Identical to the compiled wheel
    # except the first-party modules aren't Nuitka-compiled. pip uses the compiled
    # wheel where it matches, this otherwise (any Python 3.11+/OS).
    if args.also_source:
        (work / "fallback").mkdir()
        run([sys.executable, "-m", "wheel", "pack", str(tree), "-d", str(work / "fallback")])
        fb = next((work / "fallback").glob("*.whl"))
        shutil.copy(fb, outdir / fb.name)
        print(f"[build] source fallback -> {outdir / fb.name}")

    # 3a. research.py -> _sr_core.<abi>.pyd, then replace research.py with the shim
    core_src = comp / "_sr_core.py"
    shutil.copy(tree / "research.py", core_src)
    core_mb = core_src.stat().st_size / (1024 * 1024)
    print(f"[build] compiling research.py -> _sr_core ({core_mb:.1f} MB core — slow) …")
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
