# Super Agent — drive Super Research from chat (Hermes / OpenClaw)

Lets a chat runtime (Hermes / OpenClaw) drive **Super Research** as a *headless
session of your account*. You install a small `/sr` skill + a local loopback
bridge, sign in once with Google, and then run / track research from chat —
every run shows up in the web app like a normal chat.

- **Research-only.** Run / track / fetch research. It can **never** control
  devices (add / remove / pair / share stay owner-only in the app).
- **One agent per account** (owner or sharer).
- **No dedicated worker, no separate logins, no identity minting.** It uses your
  account's existing paired devices, on the app's normal Firestore plane.

---

## Install

One command, run in your chat runtime's environment — or grab it from the page at
**https://superresearch.io/agent-install**:

```sh
pipx run superresearch-agent connect      # the published package
```

`connect` is a branded, interactive flow — **Detect → Choose → Install → Go
live** — that finds your runtime (native on this OS, or inside WSL), copies the
`/sr` skill in, offers to keep a background bridge running on every login, and
signs you in. Then, in chat:

```
/reload-skills          # Hermes only, once, so /sr registers
/sr login               # sign in (approve on your phone)
/sr research <topic>    # …and you're running
```

**Install straight from chat.** Hermes / OpenClaw can run the command themselves —
just ask ("install Super Research"), and the agent runs `pipx run
superresearch-agent connect` and relays the sign-in link. (The runtime's
`/skills` marketplace command is terminal-only and doesn't work over a chat
platform — *running the command* does.) The machine-readable companion is at
**https://superresearch.io/agent-install.json** (command + flags + steps).

**No backend host yet?** The agent orchestrates from chat; the research pipeline
runs on a paired computer. If you don't have one, say **"install Super Research
here"** (`/sr install`) to install the backend on this machine from chat, then
pair it: run `superresearch --pair` on the host, read the 8-char code to chat,
and `device add <code>`.

---

## Use it from chat (`/sr`)

The runtime registers the skill as one slash command — **`/sr`** — and the action
follows it (natural phrasing works too: "research the EV market", "send me the
podcast"):

```
/sr login                        sign in (account session)      ·   /sr logout
/sr research <topic>             start a run
/sr status [title]               a run's progress + permanent share links
/sr updates                      all active runs + their links
/sr podcast [title]              the run's audio, sent as a native voice message
/sr retry [title]                resume a run waiting on a decision / error
/sr skip [phases] [--run title]  trim phases (brief/podcast/video/report) or resolve a blocker
/sr stop [title]                 gracefully stop a run (keeps results + chat)
/sr device                       list devices  ·  device use <name>  ·  device add <code>  ·  device remove <name>
```

A bare `/sr` is the welcome + help. **Every account action needs `/sr login`
first** — the agent operates as an authorized session on your account, so it's
signed in before it can list devices, start research, or pair.

### Versions + updates (from chat)

```
/sr version        agent + Super Research backend versions, with a "⬆ newer available" nudge
                   (also surfaced on the welcome)
/sr update         update the Super Research BACKEND on the connected device
/sr agent-update   update the chat AGENT itself (package + skill + bridge)
/sr install        install the backend on this host (turn this PC into a research host)
```

`update` / `agent-update` reply "already up to date" when nothing newer is
published, instead of a pointless reinstall.

---

## Reachability — the bridge runs WITH the runtime

The bridge binds **loopback only**, so it can only be reached by a runtime on its
*own* machine — which is why `connect` co-locates them:

- **Co-located** (runtime native on the same OS — Win+Win / Linux+Linux /
  macOS+macOS) → shares loopback, **zero setup**.
- **WSL runtime** → `connect` detects it and runs the install **inside WSL** (the
  bridge then shares WSL's loopback with the runtime) — no Windows↔WSL
  networking, no `.wslconfig`. Each side-effecting step still waits for your Y.
- **Different machine** → can't reach a loopback-only bridge → **unsupported by
  design** (exposing the bridge on the network would break its security model).

---

## Keep it always-up / tear it down

```sh
agent resurrect    # pin to login + start now, windowless (Scheduled Task / systemd --user / launchd)
agent retire       # stop the background bridge + remove the logon pin
agent serve        # run the bridge in THIS terminal (foreground) instead
agent stop         # stop the running bridge
agent disconnect   # FULL teardown — remove the skill from the runtime AND sign out
                   #   (the CLI twin of the app's "Revoke"); use `agent retire` too to also drop the bridge
```

The account session + device selection persist, so a restart resumes without
re-login.

> **`agent <cmd>` shorthand** — equivalently:
> `superresearch agent <cmd>` (installed backend; delegates to `pipx run
> superresearch-agent <cmd>`), `pipx run superresearch-agent <cmd>` (standalone),
> or `python research.py agent <cmd>` (from a backend source checkout). Pick
> whichever matches how things are set up.

---

## Sign-in

`agent login` (and `/sr login`) default to the **web app**
(`https://superresearch.io/agent-auth`) — the same page everywhere — brokering an
approve-on-your-phone flow that makes only **outbound** calls (no localhost
needed). `agent login --local` is the host-local Google page
(`http://localhost:9876/login`) fallback for dev / no-network.

```sh
agent login --remote --runtime hermes
#  → Open  https://superresearch.io/agent-auth  → sign in → tap Authenticate
#  ✓ Connected as you@…
```

`agent serve` writes a durable, rotating operational log to
`~/.super-agent/bridge.log` (request + run-lifecycle lines; never a token);
add `-v` / `--verbose` for DEBUG.

---

## Developing (from a backend source checkout)

You don't need the published package to hack on it. Run the agent through the
backend's **`agent` front door** — it never imports the agent package, it just
fronts it, so the agent stays an isolated sub-package + process:

```sh
cd research-automate
python research.py agent <command>      # connect / serve / login / status / doctor / device / research / …
python research.py agent --help         # full command list
python research.py agent                # bare → smart entry: status if set up, else connect
```

Standalone `agent` command + the test suite:

```sh
cd research-automate/agent
pip install .[dev]      # standalone `agent` entry point + pytest + ruff
python -m facade <cmd>  # or run module-style without installing
python -m pytest        # the test suite
ruff check .
```

The agent's only runtime deps (`requests`, `keyring`) already ship in the
backend's `requirements.txt`. Requires **Python 3.11+**.

---

## The "nothing breaks" contract

A **separate process** that never touches the existing app:

- No import of, or write to, `research-automate` or `research-app`.
- Its own secret-store namespace (`super-agent`, `~/.super-agent`) — **never** the
  device daemon's `super-research` keystore. The account refresh token and the
  device refresh token are different Firebase users; isolating them means a
  refresh here can't disturb a paired device.
- Writes only what a normal account client may write under the **existing**
  Firestore rules: research docs under your own tree + device-queue `start` docs
  where you're a member. No rules change, no keystore change, no queue / claim /
  pipeline change.

---

## Layout

```
facade/
  config.py          public Firebase config + bridge host/port/store + FE base
  store.py           secure session store (keyring + 0600 file fallback)
  prefs.py           non-secret prefs (selected device [uid-bound], runtime)
  session.py         AccountSession — refresh-token / custom-token → ID-token
  firestore_rest.py  minimal Firestore REST (researches/devices, upsert, enqueue, cancel)
  devicelogin.py     remote-login device-flow client (→ the SR web app broker)
  selfupdate.py      PyPI version notices + self-update (agent reconnect-from-latest;
                     backend install/update) — detached, mirrors the backend pattern
  logsetup.py        rotating-file + console logging (--verbose)
  runview.py         flatten links.{kind} → ordered events; terminal-status set
  connect.py         install the skill into a chat runtime (+ WSL hand-off)
  autostart.py       windowless logon autostart (schtasks / systemd --user / launchd)
  bridge.py          loopback HTTP server (/login, /login/remote/*, /devices, /device,
                     /research, /updates, /version, /update, /agent-install, /install-backend, …)
  web/login.html     Firebase Web SDK Google sign-in (TOTP MFA aware)
  skill/             the chat-runtime bundle (SKILL.md + scripts/sr.py + the streaming watchdog)
  cli.py             the `agent` command
```
