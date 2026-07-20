# Mac wheel build — `superresearch` 0.1.5 (cp313 / macosx_11_0_arm64)

Build the **macOS** Nuitka wheel so it's byte-consistent with the Windows (`cp314`) and
Linux (`cp312-manylinux_2_34`) wheels already built on the Windows box, then copy the one
`.whl` back to Windows so all three publish together in one release.

**You build the Mac wheel here; the Windows box publishes all three** (`uv publish`, your PyPI token).

---

## 0. Prereqs (check each)

- **Apple Silicon**: `uname -m` → `arm64`. (An Intel Mac mints `macosx_11_0_x86_64` — wrong arch, won't match the published mac line.)
- **Python 3.13 specifically**: `python3.13 --version` → `3.13.x`. The tag is derived from the *running* interpreter, so **only 3.13 yields `cp313`** (3.12→cp312, 3.14→cp314 would break the triad).
- **Xcode Command Line Tools / clang**: `xcode-select -p` returns a path and `clang --version` works (`xcode-select --install` if not).
- **nuitka + wheel installed into the 3.13 interpreter** that runs the script. Recommended isolated venv:
  ```bash
  python3.13 -m venv ~/sr_build_venv && ~/sr_build_venv/bin/pip install -U nuitka wheel
  ~/sr_build_venv/bin/python -m nuitka --version && ~/sr_build_venv/bin/python -m wheel version
  ```
- **Repo synced + clean**, on personal `master`:
  ```bash
  cd <research-automate>            # the BE repo (pyproject name = "superresearch")
  git pull --ff-only origin master  # latest master (0c9ff46 or newer)
  git rev-parse --short HEAD
  git status --porcelain            # MUST be empty
  grep -m1 '^version' pyproject.toml # MUST show: version = "0.1.5"
  ```
- **`MACOSX_DEPLOYMENT_TARGET` NOT preset**: `echo "$MACOSX_DEPLOYMENT_TARGET"` prints empty. The script sets it to `11.0` only when unset; a preset value would retag the wheel to that macOS version. (No auditwheel/patchelf needed — that's the Linux-only step.)

---

## 1. Build (no flags — ~5-6 min)

```bash
cd <research-automate>
~/sr_build_venv/bin/python tools/build_compiled.py
#   equivalently: python3.13 tools/build_compiled.py   (if system 3.13 has nuitka+wheel)
```

**Do NOT pass any flags.** `--outdir` defaults to `dist/`, `--macos-target` defaults to `11.0`.
Never pass `--also-source` (emits a readable py3-none-any source fallback — must never be
published) and never `--compile-auth` (keep `auth/` as source, same as win/linux).

**Expected output:** `dist/superresearch-0.1.5-cp313-cp313-macosx_11_0_arm64.whl`

---

## 2. Verify (must all pass before bringing it back)

```bash
W=dist/superresearch-0.1.5-cp313-cp313-macosx_11_0_arm64.whl

# 1) Version + tinytag dep
unzip -p "$W" 'superresearch-0.1.5.dist-info/METADATA' | grep -E '^(Version:|Requires-Dist: tinytag)'
#   expect:  Version: 0.1.5   /   Requires-Dist: tinytag>=2.0

# 2) Source hidden (compiled): _sr_core + the 4 TOP_MODULES ship ONLY as .so; research.py is the tiny shim
unzip -l "$W" | grep -E '_sr_core|\.so$|research\.py|models\.py|prompts\.py|vision\.py|narrate\.py|selfheal\.py'
#   expect: _sr_core.cpython-313-darwin.so + models/prompts/vision/narrate .cpython-313-darwin.so
#           research.py present but TINY (the shim) ; selfheal.py present as SOURCE (~53KB, same on win/linux)
#           NO models.py/prompts.py/vision.py/narrate.py source entries
unzip -p "$W" research.py | wc -l    # a few dozen lines (the shim), NOT ~52,952 (raw source)

# 3) --version smoke (throwaway venv; --no-deps ok — the shim answers --version before importing _sr_core)
python3.13 -m venv /tmp/sr_verify && /tmp/sr_verify/bin/pip install --no-deps "$W"
/tmp/sr_verify/bin/superresearch --version    # ->  "  Super Research  v0.1.5"
rm -rf /tmp/sr_verify
```

If you see a large `research.py` or a `*-py3-none-any.whl`, the build used the wrong mode — STOP.

---

## 3. Bring it back

Copy the single file **`dist/superresearch-0.1.5-cp313-cp313-macosx_11_0_arm64.whl`** to the
Windows box at `research-automate/dist/`. That completes the 3-wheel set:

| Platform | File |
|---|---|
| Windows | `dist/superresearch-0.1.5-cp314-cp314-win_amd64.whl` *(built)* |
| Linux | `dist/manylinux/superresearch-0.1.5-cp312-cp312-manylinux_2_34_x86_64.whl` *(built)* |
| **macOS** | `dist/superresearch-0.1.5-cp313-cp313-macosx_11_0_arm64.whl` *(you build this)* |

Then publish all three per-file with `uv publish` (see `release/PUBLISH.md` / the publish notes).
**Never** publish a `py3-none-any` fallback (ships readable source) or the raw `…linux_x86_64.whl` (PyPI rejects the tag).

---

## Consistency (why all three are equivalent)

**Must match** across all platforms (all guaranteed by the same tracked `tools/build_compiled.py` at a clean HEAD):
- Same 5 Nuitka-compiled first-party modules: `research.py`→`_sr_core` + `models`/`prompts`/`vision`/`narrate`.
- Same source-shipped set: `selfheal.py` (in py-modules but not compiled), `auth/`, `scripts/` stay readable source everywhere.
- Same launcher **shim** replacing `research.py` (byte-identical constant).
- Same dropped admin scripts (`scripts/dump_push_audit.py`, `scripts/admin_cleanup_stale_ongoing.py` absent from every wheel).
- Same metadata/deps: `Version: 0.1.5` + full `Requires-Dist` incl `tinytag>=2.0` (inherited from `pyproject`).

**Legitimate per-platform differences** (expected, not inconsistencies):
- python-minor tag: mac `cp313` / win `cp314` / linux `cp312` (each box builds on its own interpreter).
- platform tag: `macosx_11_0_arm64` / `win_amd64` / `manylinux_2_34_x86_64`.
- extension form: mac/linux `.so` vs win `.pyd` (module names identical).
- Linux alone needs the `auditwheel repair` post-step; mac + win emit the final wheel directly.
