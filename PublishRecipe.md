# PublishRecipe — build the macOS wheel + publish Super Research

**Audience:** the Claude Code instance running on Sammy's Mac (to build the macOS
backend wheel), and Sammy on Windows (to copy the wheel in + publish).

**Goal:** Super Research ships **per-platform, source-hidden (Nuitka-compiled)**
backend wheels. Windows (`cp314`) + manylinux (`cp312`) are already built and
sitting in `dist/`. The **only** missing one is **macOS Apple-Silicon (`cp313`,
arm64)** — this recipe builds it. The agent wheel is pure-Python (one wheel for
all OSes) and is already built. The user runs every `uv publish` (and enters the
token); **Claude never enters publish tokens.**

The publish set (versions): backend `superresearch` **0.1.1** (win + manylinux +
mac) and agent `superresearch-agent` **0.1.6**. The backend source (`research.py`
+ the compiled siblings) is **frozen since commit `de815bc`** — every commit on
`master` since is agent-only — so building from `master` HEAD yields the correct
0.1.1 backend.

---

## PART A — Build the macOS wheel (run on the Mac)

> Repo (personal, made public temporarily): **https://github.com/syamnadhg/dg-research-backend.git**
> If you (the Mac's Claude) are reading this, you've already cloned it — just run from the repo root.

### A0. Prerequisites (check / install)
- **Apple Silicon Mac** (arm64). Confirm: `uname -m` → `arm64`.
- **Python 3.13** specifically (the wheel tag MUST be `cp313` to match the locked
  macOS target). Confirm a 3.13 is available:
  - `python3.13 --version` → `Python 3.13.x`, **or** install one: `uv python install 3.13` (then use `uv run --python 3.13 …`), or `brew install python@3.13`, or python.org.
  - ⚠️ Do **not** build with 3.12 / 3.14 — that produces a `cp312`/`cp314` wheel that won't match the macOS target and macOS users on 3.13 couldn't install it.
- **Xcode Command Line Tools** (provides `clang`, which Nuitka needs):
  `xcode-select -p` should print a path; if not: `xcode-select --install` (and wait for it to finish).
- **git** (to clone, if not already done).

### A1. Clone (skip if already cloned)
```bash
git clone https://github.com/syamnadhg/dg-research-backend.git
cd dg-research-backend
git checkout master && git pull        # build from HEAD; backend is frozen since de815bc
```

### A2. Make a clean Python 3.13 build venv
A stdlib venv includes `pip` (the build script shells out to `python -m pip` and
`python -m wheel`):
```bash
python3.13 -m venv .buildvenv
source .buildvenv/bin/activate
python --version                       # MUST say 3.13.x
pip install --upgrade pip
pip install nuitka wheel setuptools
```
(Build deps only — the backend's heavy runtime deps are NOT needed: the script
builds the source wheel with `--no-deps` and Nuitka compiles the modules without
importing them.)

### A3. Build
```bash
python tools/build_compiled.py
```
- This compiles `research.py` → `_sr_core.<abi>.so` (the slow step, ~5–8 min for
  the 2.1 MB core) plus `models/prompts/vision/narrate`, replaces `research.py`
  with a tiny readable launcher shim, repacks, and retags the wheel
  `cp313-cp313-macosx_<ver>_arm64`.
- It prints `[build] DONE -> <path>` at the end.

### A4. Locate + report the wheel
```bash
ls -la dist/superresearch-0.1.1-cp313-cp313-macosx_*_arm64.whl
```
**→ Report the absolute path of that `.whl` to Sammy.** That's the deliverable.
(The `<ver>` in `macosx_<ver>_arm64`, e.g. `11_0`, depends on the deployment
target — note the exact filename when you report it.)

### A5. (Recommended) Sanity-check the wheel before handing it off
The `--version` path runs on the lazy launcher shim (no heavy import), so a
`--no-deps` install verifies the wheel is sound without installing the full
dependency tree:
```bash
python3.13 -m venv .checkvenv && source .checkvenv/bin/activate
pip install --no-deps "dist/superresearch-0.1.1-cp313-cp313-macosx_*_arm64.whl"
superresearch --version                # → "Super Research  v0.1.1"  (instant)
python -c "import zipfile,glob; z=zipfile.ZipFile(glob.glob('dist/superresearch-0.1.1-cp313-cp313-macosx_*_arm64.whl')[0]); names=z.namelist(); print('cores:', sorted(n for n in names if n.endswith('.so'))); print('shim research.py present:', 'research.py' in names)"
deactivate
```
Expect: `superresearch --version` prints `Super Research  v0.1.1`; the `.so`
list includes `_sr_core…`, `models…`, `narrate…`, `prompts…`, `vision…`; and the
readable `research.py` shim is present. If so, the wheel is good.

### Troubleshooting (Mac)
- **Wrong tag** (`cp312`/`cp314` instead of `cp313`): you built with the wrong
  Python. Recreate the venv with 3.13 and rebuild.
- **`clang: command not found` / compiler errors**: install Xcode CLT
  (`xcode-select --install`).
- **Nuitka prompts to download something**: the script passes
  `--assume-yes-for-downloads`; if a prompt still appears, accept it.
- **`pip: command not found`** inside the venv: you used a `uv venv` (no pip) —
  use the stdlib `python3.13 -m venv` as in A2, or `uv pip install pip` first.

---

## PART B — Copy the wheel into `dist/` (on Windows)

Transfer the macOS `.whl` from the Mac (AirDrop / iCloud / USB / scp) into the
Windows backend repo's `dist/` directory:
```
C:\Users\syamn\research-dg\Automate\DG Research\research-automate\dist\
```
After copying, `dist/` should contain all three backend wheels + the agent wheel:
- `dist\superresearch-0.1.1-cp314-cp314-win_amd64.whl`
- `dist\manylinux\superresearch-0.1.1-cp312-cp312-manylinux_2_34_x86_64.whl`
- `dist\superresearch-0.1.1-cp313-cp313-macosx_<ver>_arm64.whl`   ← the new one
- `agent\dist\superresearch_agent-0.1.6-py3-none-any.whl`

---

## PART C — Publish (on Windows, your PyPI token)

From the backend repo root:
```powershell
cd "C:\Users\syamn\research-dg\Automate\DG Research\research-automate"

# backend (project: superresearch)
uv publish "dist\superresearch-0.1.1-cp314-cp314-win_amd64.whl"
uv publish "dist\manylinux\superresearch-0.1.1-cp312-cp312-manylinux_2_34_x86_64.whl"
uv publish "dist\superresearch-0.1.1-cp313-cp313-macosx_<ver>_arm64.whl"   # exact mac filename from A4

# agent (project: superresearch-agent) — pure-python, one wheel for all OSes
uv publish "agent\dist\superresearch_agent-0.1.6-py3-none-any.whl"
```

- ⛔ **Do NOT publish** `dist\superresearch-0.1.1-cp312-cp312-linux_x86_64.whl` —
  PyPI rejects a plain `linux_x86_64` tag; the `manylinux` wheel is its
  publishable twin.
- Your token needs access to **both** PyPI projects (`superresearch` +
  `superresearch-agent`). `uv` prompts for the token (or set `UV_PUBLISH_TOKEN`).
- The three backend wheels are all version `0.1.1` — uploading them in separate
  `uv publish` calls is fine; PyPI accepts multiple platform wheels per version.

---

## After publishing — quick live check
```bash
# backend resolves on each platform's matching Python; agent is universal:
uvx superresearch-agent@0.1.6 --version       # → agent 0.1.6
# on a mac (py3.13): pipx install superresearch ; superresearch --version → v0.1.1
```

> Then remember to make the repo **private** again (you only opened it so the
> Mac could clone).

---

*Once this recipe has served its purpose (mac wheel built + everything published),
it can be deleted — like the prior one-off PublishRecipe. Per repo convention,
recipes are kept only while live.*
