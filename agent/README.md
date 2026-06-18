# Super Agent — drive Super Research from chat (Hermes / OpenClaw)

Lets a chat runtime (Hermes / OpenClaw) drive **Super Research** as a *headless
session of your account*. You sign in once with Google (`/sr login`); the bridge
then enqueues research runs on your account's existing devices, and every run
shows up in the web app like a normal chat.

- **Research-only.** It can run / track / fetch research. It can **never**
  control devices (add / remove / pair / share) — that stays owner-only.
- **One agent per account** (owner or sharer).
- **No dedicated worker, no separate logins, no identity minting.** It uses the
  account's existing devices, on the app's normal Firestore plane.

Design source of truth: `../SuperAgentRecipe.md`.

## The "nothing breaks" contract

This package is a **separate process** and never touches the existing app:

- No import of, or write to, `research-automate` or `research-app`.
- Its own secret-store namespace (`super-agent`, `~/.super-agent`) — **never**
  the device daemon's `super-research` keystore. The account refresh token and
  the device refresh token are different Firebase users; isolating them means a
  refresh here can never disturb a paired device.
- Writes only what a normal account client may write under the **existing**
  Firestore rules: research docs under your own tree + device-queue `start`
  docs where you're a member. No rules change, no keystore change, no queue /
  claim / pipeline change.

## Running it (no install)

Run the agent as a **`research.py` command** — same front door as the rest of
the backend, from the repo root, **no install and no editable mode**:

```sh
cd research-automate
python research.py agent <command>      # e.g. agent connect / agent serve / agent login
python research.py --agent <command>    # flag-style alias (consistent with --pair/--serve)
python research.py agent                # bare → smart entry: status if set up, else connect
python research.py agent --help         # the full command list
```

The agent's only deps (`requests`, `keyring`) already ship in the backend's
`requirements.txt`, so once the backend is set up (`pip install -r
requirements.txt`) there is **nothing extra to install**. Requires **Python
3.11+**.

> **Throughout this README, `agent <command>` is shorthand for
> `python research.py agent <command>`.**

The code itself lives in this isolated sub-package (`research-automate/agent/`,
its own process + its own two deps); `research.py` only *fronts* it so it's
invoked consistently — it never imports the package.

<details><summary>Optional — a bare <code>agent</code> command / dev setup</summary>

If you'd rather type a bare `agent` (outside the backend) or run the tests:

```sh
cd research-automate/agent
pip install .                      # adds a standalone `agent` command (entry point)
python -m facade <command>         # or run module-style, no install
pip install .[dev]                 # + test deps (pytest, ruff)
pip install -r requirements-dev.txt
```

`requirements.txt` / `requirements-dev.txt` here mirror `pyproject.toml` for a
fresh venv. The `python research.py agent` path above needs none of this.
</details>

## Use it from chat (Hermes / OpenClaw)

Install the Super Research skill into your chat runtime, then drive everything
with slash commands:

```sh
cd research-automate
python research.py agent connect    # branded 4-step flow; detects Windows + WSL runtimes
# step 4 offers to run the bridge in the background now + on every login
# then in chat:  /reload-skills (once) → /sr login → approve on phone → /sr research <topic>
```

`agent connect` is an interactive, branded flow — **Detect → Choose → Install →
Go live** — that finds your chat runtime on **Windows** (`~/.hermes`,
`~/.openclaw`) *and* inside **WSL** (`\\wsl.localhost\<distro>\home\<user>\…`),
lets you pick when more than one is found, copies a small dependency-free skill
(a `SKILL.md` + a `scripts/sr.py` client that calls the bridge over loopback)
into the runtime's skills dir, and offers to pin the always-up bridge.

The runtime registers a skill as a single slash command (`/<skill-name>`), so the
skill is **`/sr`** and the action follows it: `/sr login`, `/sr research <topic>`,
`/sr status [id]`, `/sr device [use <id>]`, `/sr podcast [id]`, `/sr skip <id>
<phases>`, `/sr cancel <id>`, `/sr logout`; a bare **`/sr`** is the welcome / help.
Natural phrasing works too ("research Tesla 2025", "send me the podcast"). It's
research-only — it can never control devices.

> **After connecting, run `/reload-skills` once in your chat** (the gateway caches
> its skill scan) so `/sr` registers without restarting the runtime.

**Reachability — Model A: the bridge runs WITH the runtime.** The bridge binds
**loopback only**, so it can only be reached by a runtime on its *own* machine —
which is why `connect` co-locates the bridge with the chat runtime:

- **Co-located** (runtime native on the same OS as the bridge — Win+Win,
  Linux+Linux, macOS+macOS) → shares loopback, **zero setup**.
- **WSL runtime** → the bridge must run **inside WSL** too. `connect` detects a
  WSL runtime and **offers to run connect there for you** — `pipx run
  superresearch-agent connect` inside the distro (or prints the command, with a
  `python research.py agent connect` backend-checkout fallback for before the
  package is on PyPI). The bridge then shares WSL's loopback with the runtime —
  no Windows↔WSL networking, no `.wslconfig`.
- **Different machine** → can't reach a loopback-only bridge → **unsupported by
  design** (exposing the bridge on the network would break its security model).

> Each side-effecting step still waits for your Y — `connect` never installs or
> runs anything inside WSL on its own.

**Keep it always-up.** `resurrect` pins a windowless logon autostart (Windows
Scheduled Task) **and** starts the bridge now, so it returns after a reboot; the
account session + device selection persist, so a restart resumes without
re-login. `retire` is the inverse.

```sh
agent resurrect    # background + on every login (windowless); starts it now too
agent retire       # stop the background bridge + remove the logon pin
agent serve        # foreground (this terminal) instead of background
agent stop         # stop the running bridge
```

**Disconnect.** `agent disconnect` is a full teardown — it removes the skill from
the runtime **and** signs out (the CLI twin of the app's **Revoke**). Use
`agent retire` as well if you also want the background bridge gone.

## P0 — connect + prove the plane

```sh
agent serve            # start the loopback bridge (127.0.0.1:9876)
agent login            # sign in on the SR web app (superresearch.io); --local = host page
agent status           # → "Signed in as you@…"
agent doctor           # health + token-refresh + connectivity checks
agent verify           # reads your researches + lists reachable devices
agent verify --enqueue --device <id> --topic "Tesla 2025"   # starts a real run
```

`agent verify` (no `--enqueue`) is read-only. With `--enqueue` it creates a
research doc + a device-queue start doc — a real pipeline run that will appear
as an app chat.

## P1 — remote sign-in + operational logging

**Remote sign-in (no localhost needed).** Approve from your phone via the
Super Research web app — the bridge brokers an OAuth device-style flow and makes
only outbound calls (see `SuperAgentRecipe.md` §11a):

```sh
agent login --remote --runtime hermes
#  → Open  https://superresearch.io/connect-agent  and enter code:  AB-12
#  (sign in to Super Research on your phone, tap Approve)
#  ✓ Connected as you@…
```

**`agent login` now defaults to the web app** (`superresearch.io` — the same page as
`/sr login` from chat + the connect Step 4 "Sign in"), so sign-in is one consistent
flow everywhere. The local Google page (`http://localhost:9876/login`) is the
`agent login --local` host-local fallback for dev / no-network.

**Logging.** `agent serve` writes a durable, rotating operational log to
`~/.super-agent/bridge.log` (request + run-lifecycle lines; never a token).
Add `-v` / `--verbose` (before or after the subcommand) for DEBUG.

**Pick a device.** List the devices your account can reach and choose which one
runs your research (the selection persists across restarts in
`~/.super-agent/prefs.json`):

```sh
agent device                 # list (→ marks the selected one; (owned)/(shared))
agent device use <deviceId>  # switch the target device
```

`agent research`/`/sr research` resolves the device as: an explicit id → your
selection → the sole reachable device → an error asking you to pick one.

**Run, track, cancel.**

```sh
agent research "Tesla 2025 outlook"   # start a run → prints a run id immediately
agent runs                            # list recent runs (status + phase)
agent run [id]                        # one run's status + links (no id = latest)
agent watch [id]                      # stream per-phase links live until it finishes
agent skip <id> <phases…>             # skip phases (1/3/4/5 or brief/podcast/video/report)
agent cancel <id>                     # stop a run (queued → dropped; running → stopped)
```

`agent skip` tunes the run's config (Brief / Podcast → `skippedPhases`; Video →
`videoEnabled` off; Report → `emailEnabled` off); the device applies it when each
phase is reached.

`agent watch` polls and prints each new link (Brief → ChatGPT/Gemini/Claude →
NotebookLM/Audio → YouTube → Doc) as the device produces it, then stops at a
terminal status. The same signal feeds a runtime's streaming cron via
`GET /updates` (account-wide active runs + their current links) — a poller
dedups by `(runId, kind)`. (No `?since=` watermark: the backend doesn't bump
`updatedAt` on a per-phase link write, so the current link set is returned every
poll and deduped client-side.) Cancel writes a single `action:"cancel"` to the
run's device queue — dropped if queued, stopped if running.

> The web app's broker routes (`/api/agent/login/{start,approve,poll}` +
> `/connect-agent`) are built separately under review; this package is only the
> outbound client.

## Layout

```
facade/
  config.py          public Firebase config + bridge host/port/store + FE base
  store.py           secure session store (keyring + 0600 file fallback)
  prefs.py           non-secret prefs (selected device [uid-bound], runtime)
  session.py         AccountSession — refresh-token / custom-token → ID-token
  firestore_rest.py  minimal Firestore REST (researches/devices, upsert, enqueue, cancel)
  devicelogin.py     remote-login device-flow client (→ the SR web app broker)
  logsetup.py        rotating-file + console logging (--verbose)
  runview.py         flatten links.{kind} → ordered events; terminal-status set
  connect.py         install the skill into a chat runtime
  bridge.py          loopback HTTP server (/login, /login/remote/*, /devices,
                     /device, /research, /updates, …)
  web/login.html     Firebase Web SDK Google sign-in (TOTP MFA aware)
  skill/             the chat-runtime bundle (SKILL.md + scripts/sr.py)
  cli.py             the `agent` command
```
