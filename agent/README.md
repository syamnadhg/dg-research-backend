# Super Agent — drive Super Research from chat (Hermes / OpenClaw)

Lets a chat runtime (Hermes / OpenClaw) drive **Super Research** as a *headless
session of your account*. You install a small `/sr` skill + a local loopback
bridge, sign in once with Google, and then run / track research from chat —
every run shows up in the web app like a normal chat.

- **Research + device management.** Run / track / fetch research, and add (pair
  by access code), switch, or remove Research Computers from chat — plus find a
  computer somebody else offers publicly and ask its owner for access, and, for a
  computer you own, answer the people asking and set whether strangers can find
  it at all. Unlinking a computer you own rotates its access code and the reply
  hands you the new one. Revoking one sharer's access stays owner-only in the
  web app.
- **Support logs, on request and never by default.** A Research Computer can
  package the logs of *your* runs for support, and the agent's own log on this
  host can go too — or on its own. Both print what would leave before anything
  does.
- **One agent row per install.** It signs in as you (owner or sharer), and each
  host you connect shows as its own renamable, revokable row in the app's
  *Shared with* popup — a second host adds a row rather than replacing one.
- **No dedicated worker, no separate logins, no identity minting.** It uses your
  account's existing paired devices, on the app's normal Firestore plane.

---

## Install

One command, run in your chat runtime's environment — or grab it from the page at
**https://superresearch.io/skills** (the old `/agent-install` 308-redirects there):

```sh
pipx run --no-cache superresearch-agent connect      # the published package
```

`connect` is a branded, interactive flow — **Detect + choose → Install the skill
→ Run on startup → Sign in** — that finds your runtime (native on this OS, or
inside WSL), copies the `/sr` skill in, offers to keep a background bridge
running on every login, and signs you in. Then, in chat:

```
/reload-skills          # Hermes only, once, so /sr registers
/sr login               # sign in (approve on your phone)
/sr research <topic>    # …and you're running
```

**Install straight from chat.** Hermes / OpenClaw can run the command themselves —
just ask ("install Super Research"), and the agent runs `pipx run
--no-cache superresearch-agent connect` and relays the sign-in link. (The runtime's
`/skills` marketplace command is terminal-only and doesn't work over a chat
platform — *running the command* does.) The agent-facing companion is
**https://superresearch.io/skills.md** — the page to hand an agent as a link
("Install Super Research from superresearch.io/skills.md"); it tells the agent to
run that one command, register the skill, and sign you in, and nothing else.

**No backend host yet?** The agent orchestrates from chat; the research pipeline
runs on a paired computer. If you don't have one, say **"install Super Research
here"** (`/sr install`) to install the backend on this machine from chat, then
pair it: run `superresearch --pair` on the host, read the 8-char **access code**
off its screen to chat, and `device-add <code>`. The setup asks its own
questions on the host — among them, in a step of its own, whether other people
may **find** that machine, which defaults to *no* — and the agent answers none
of them; `device-visibility` is how that one changes afterwards. (Or ask to use
somebody else's machine instead — see **Computers other people offer**.)

---

## Use it from chat (`/sr`)

The runtime registers the skill as one slash command — **`/sr`** — and the action
follows it (natural phrasing works too: "research the EV market", "send me the
podcast"):

```
/sr login                        sign in (account session)      ·   /sr logout
/sr research <topic>             start a run   (--no-video · --no-email · --device <id>)
/sr status [title]               a run's progress + permanent share links
/sr updates                      runs you started from chat (newest 20, any status) + their links
/sr list                         every research on the account, any status
/sr podcast [title]              the run's audio, sent as a native voice message
/sr pause [title]                hold a run (resumable)         ·   /sr resume [title]
/sr retry [title]                resume a run waiting on a decision / error
/sr skip [phases|agents] [--run title]
                                 trim phases (brief/podcast/video/report) or P2 research
                                 agents (chatgpt/gemini/claude); bare = clear the blocker
/sr stop [title]                 gracefully stop a run (keeps results + chat; `cancel` = alias)
/sr devices                      list devices  ·  device-use <name>  ·  device-add <code>  ·  device-remove <name>
/sr devices-public               computers other people offer   ·   device-ask <name|id>
/sr device-requests              who's asking for yours, and what you're waiting on
/sr device-approve [person]      ·   device-deny [person]   ·   device-visibility public|private [name]
/sr send-logs                    package logs for support — prints the plan, sends nothing
```

A bare `/sr` is the welcome + help. **Every account action needs `/sr login`
first** — the agent operates as an authorized session on your account, so it's
signed in before it can list devices, start research, or pair.

Nothing has to match a row: anything the runtime can't place goes to the client's
own `do "<the message, verbatim>"`, which resolves the intent **in code** — so a
plain sentence runs the right command (or asks the one missing thing) rather than
falling back to the chat runtime's own tools.

**Which computer a run goes to** is one decision, made in one place, and the
sign-in auto-start uses the identical ladder: your saved selection → the sole
computer on the account → the sole one that's **online** → otherwise it asks,
and says *why* (your last computer isn't reachable, versus you've never picked).
**Online** rests on the machine's own heartbeat, read from the server-stamped
copy where there is one — one clock for the writer and the reader — and falling
back, permanently, to the older machine-clock stamp for a computer that hasn't
upgraded. Two disagreeing clocks are how a switched-off computer reads online,
which is the one thing this rung must not get wrong.

Two refusals are deliberate. A computer part-way through being set up again is
named and refused rather than quietly swapped for another — your research running
somewhere you didn't choose is the same broken promise with a surprise on top —
and it keeps your selection, because the machine is still yours. An account with
no computer at all routes to the empty state below, never to "pick one from an
empty list".

### What arrives in chat on its own

Almost nothing, and that is the design. A **streaming watchdog** — armed by the
client itself for the chat you're in (`arm-stream`), and scoped to the runs *you*
started from chat — posts unprompted for exactly three things: **one** completion
message per run, carrying every phase's permanent, non-revocable Super Research
link plus "the results have been emailed"; a run that **needs you** (a sign-in, a
verification, a snag, an error), with how to answer it from chat; and a run that
was stopped or cancelled, from either surface.

It deliberately does **not** narrate phase by phase — progress and the links so
far are what `/sr status` is for — and it prints nothing at all when there's
nothing new, so the chat is never spammed. The revocable platform links
(NotebookLM / YouTube / the final Doc) are never pushed, because they don't open
for someone who isn't signed in. If its ticking stops, the next `status` /
`updates` you ask for re-arms it rather than letting the chat go quiet for good.

### Computers other people offer

Being **findable** is discovery, not access. `device-visibility public` lists a
computer you own for other signed-in people, who can then *ask* for it; you
approve each person by hand, and `device-visibility private` takes it off the
list again (an access code still lets someone in without asking you). From the
other side, `devices-public` browses what's on offer and `device-ask` puts you in
that owner's queue — they see your name, or your email if you haven't set one,
and nothing happens on their machine until they say yes.

**Where that setting starts is not here.** The machine's own `--pair` asks it
during setup, in a step of its own, and the answer defaults to *no*; a computer
paired before that question existed carries no answer at all and reads
**private**, like every other absent one. Afterwards three surfaces change it,
all three writing the same single field on that machine's row —
`device-visibility` from chat, the owner's toggle on the app's Account page, and
`superresearch --visibility public|private` on the machine itself (bare
`--visibility` prints where it stands and changes nothing).

`device-requests` prints **both halves** of the queue and never sums them: people
waiting on your computers first, then what you're waiting on from other people.
`device-approve` / `device-deny` answer the first half — a **no** blocks that
person asking again for a week, and handing them the access code is still a way
back if you change your mind.

Once you're in, **starting a run tells that machine's owner** — the same notice
their browser sends when a run is submitted from the web app, now sent by the
agent too, so a run you fire from chat is no quieter than one fired from a tab.
It can name you because the agent is signed in as *you*, not as a machine. On a
computer you own there's nobody to tell, and no notice goes out.

⚠ These verbs take their arguments differently on the two surfaces, on purpose.
In **chat** the person and the machine are optional — with one person waiting or
one computer owned, the client picks; with several it prints the queue rather
than guessing. In the **terminal** everything is named by **id**
(`agent device approve <deviceId> <requesterUid>`, `agent device visibility
<deviceId> public|private`), because a queue row's label is a snapshot taken the
day somebody asked and falls back to a word shared by everyone the app couldn't
look up. `agent device requests` prints the whole command for each row.

An account with **no** computer is not a dead end. Every screen that reports it
renders the one empty state — there's no computer here · add your own with an
access code · or ask to use somebody else's — and the full ones **list** the
public computers on offer, because "ask for a public one" with no list is advice
rather than a next step.

### Sending logs to support

`send-logs` is **always two steps**. The bare command prints exactly what would
leave that computer — which runs, how big, who can read them — and sends nothing;
only an explicit confirm sends (`--confirm` from chat, a `y` at the prompt, or
`-y` in the terminal). What comes back is an 8-character **support code** to
quote.

- **Your runs, and nothing else.** The Research Computer decides what matches the
  person asking, so on a shared machine this never hands over somebody else's
  research. The plan numbers every run; `--runs` takes those numbers or the run
  names, and `--runs all` is everything listed.
- **`--machine`** adds that computer's *own* logs — its pairing and sign-in
  records and its raw activity trail, which cover every run it has ever done for
  everyone who uses it. **Owner only**; anybody else is refused.
- **`--agent-log`** (and `--runs 0`, the number the plan prints for it) adds the
  log from the agent on **this** host — a connection and sign-in record, not
  research content. There is **no ownership gate** on it, it covers everyone who
  signed in through this agent, and the rotated copies go too. It can also travel
  **alone**: `--agent-log --none` sends that file and nothing else, under a
  support code of its own, with **no Research Computer involved** — which is the
  point, since the two commonest reasons to be sending it are having no computer
  paired and not being able to reach the one you have. Deleted automatically 30
  days after it arrives.
- **`--status <CODE>`** reports on a code instead of sending. **`--device`** aims
  at a computer other than the selected one — by **name or id** from chat, by
  **id** in the terminal (the same asymmetry as the device verbs above).

Terminal-only extras: `--list` (show what's held, send nothing — it never
uploads, even with `--runs 0 -y`), `-y`, `--wait <seconds>` (default 180) and
`--no-wait`. ⚠ `--no-wait` cannot carry the agent log up beside a bundle — the
plan says so before you agree, and hands you the follow-up command.

### Versions + updates (from chat)

```
/sr version        the SKILL version only, with a "⬆ newer available" nudge when a newer
                   one is published (also surfaced on the welcome). The backend's version
                   lives in the app's Settings → About — chat never states it
/sr update         update the SKILL (this chat's scripts + bridge; alias: /sr update-skill)
/sr install        install the backend on this host (turn this PC into a research host)
```

`update` (alias `update-skill`) updates **only the skill** and replies "already up
to date" when nothing newer is published. Natural language ("upgrade") routes here
too. The agent no longer updates the **backend** — a "update Super Research / the
backend" request is redirected: run `superresearch --update` on the Research
computer (idempotent), or update from the app (Settings → About → Check → Update).

In the **terminal**, `agent version` prints both lines — this package (with its
own "⬆ available" nudge) and the backend's version when Super Research is
installed on the same machine. `/sr version` additionally flags a **stale
chat-side copy**: the runtime executes its own copy of the `/sr` scripts, and
only `connect` / `update` redeploys them, so upgrading the package on the host
alone leaves chat running old behaviour.

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
agent restart      # cycle the background bridge onto the code on disk (after an upgrade) — keeps the pin
agent retire       # stop the background bridge + remove the logon pin
agent serve        # run the bridge in THIS terminal (foreground) instead
agent stop         # stop the running bridge
agent disconnect   # FULL teardown — remove the skill from the runtime AND sign out.
                   #   The app's "Revoke" is a pure sign-out and KEEPS the skill + bridge,
                   #   so this is the only full teardown; add `agent retire` to drop the bridge
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
(`http://localhost:9876/login`), a fallback for when the web app's sign-in start
fails. It is not independent of the web app: its Google window opens on
`superresearch.io` too, so it cannot help while that site is down.

```sh
agent login --remote --runtime hermes
#  → Open  https://superresearch.io/agent-auth  → sign in → tap Authenticate
#  ✓ Connected as you@…
```

**You don't have to come back and say you signed in.** The bridge parks a
one-shot "✓ Signed in" note — in memory *and* on disk, so it survives the process
that minted it — and the chat watchdog posts it proactively. A research you asked
for while signed out is routed by the **same ladder** as a fired run (above), so
that note can name the computer it started on, ask which of several should take
it, or walk the add-a-computer steps — instead of asking you to repeat the topic.

`agent serve` writes a durable, rotating operational log to
`~/.super-agent/bridge.log` (request + run-lifecycle lines; never a token);
add `-v` / `--verbose` for DEBUG. Neither a flag nor an env var reaches a
**pinned** bridge — the launcher starts it with a fixed `serve` and none of your
shell's environment — so use `agent verbose on|off`, which writes a pref read at
bridge start (`agent restart` picks it up; on a WSL runtime the command is
delegated into the distro, where that pref file lives). `agent doctor` prints
where the log is, whether anything is in it, and how to send it — and it prints
that row **before** the bridge check, because a bridge that won't start is
exactly when you need the file.

---

## Developing (from a backend source checkout)

You don't need the published package to hack on it. Run the agent through the
backend's **`agent` front door** — it never imports the agent package, it just
fronts it, so the agent stays an isolated sub-package + process:

```sh
cd research-automate
python research.py agent <command>      # connect / serve / login / status / doctor / device /
                                        # research / watch / send-logs / verbose / restart / …
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
- Writes only what a normal account client may write, every write gated by the
  Firestore rules. ⚠ The authoritative list is **not** prose — a hand-kept one
  here was wrong twice — it's the path allowlist in
  `tests/test_app_plane_unchanged.py`, read out of `firestore_rest.py`, which
  fails when a write escapes your own tree or a device you're a member of. (A
  path isn't the whole permission, which is why two more tests sit beside it:
  one pins the device-command *action* this client may ask for, one pins the
  single field name it may PATCH.) No keystore change, no queue / claim /
  pipeline change. The one rules addition is an owner-only match block for
  `users/{uid}/agentSessions/{id}` — a verbatim mirror of the existing
  `users/{uid}/sessions` block, because rules v2 doesn't inherit the parent
  `users/{uid}` allow into subcollections.
- **It never writes membership.** Pairing, unlinking and answering an access
  request all forward to `/api/devices/*` and are authorised there against your
  own session; this package holds no admin credential and can grant itself
  nothing. ⚠ `device-visibility` is the one device verb that does *not* forward —
  no web route for it exists — so it PATCHes `devices/{id}` directly with one
  field and one update mask, on the owner's own token. The rules examine that
  field's **value** — one of only two fields on the document where they do
  (`visibility`, and `joinPolicy`, the rename the rules already admit and
  nothing writes yet) — and the collection is `allow create: if false` for every
  client, so a wrong id fails rather than minting a machine. It **reads** both
  names, the old one first, because `visibility` is still what the app and the
  machines act on; a document carrying neither reads as *private*.
- **It never publishes a device row whole, either.** The device list arrives
  from the app with every field on it — including, on a machine whose access
  code was never rotated, that code in plaintext, which is the credential that
  claims the machine. So every surface that leaves this process (your devices,
  the public browse list, and the two halves of the request queue, which are two
  different lists) is a named key-set, and the exact keys are pinned by test.

---

## Layout

```
facade/
  config.py          public Firebase config + bridge host/port/store + FE base
  store.py           secure session store (keyring + 0600 file fallback)
  prefs.py           non-secret prefs (selected device [uid-bound], runtime, install id,
                     verbose switch, the parked one-shot sign-in announce)
  session.py         AccountSession — refresh-token / custom-token → ID-token
  firestore_rest.py  minimal Firestore REST (researches/devices, upsert, enqueue, cancel,
                     agentSessions, the one-field device `visibility` PATCH)
  devicelogin.py     remote-login device-flow client (→ the SR web app broker)
  branding.py        the CLI's branded screens — a self-contained mirror of the backend's
                     `--pair` look; imports nothing from the app
  selfupdate.py      PyPI version notices + skill self-update (agent reconnect-from-latest,
                     --no-cache) + disconnect cache-wipe — detached; backend updates are
                     NOT the agent's job (that's `superresearch --update` / the app)
  logsetup.py        rotating-file + console logging (--verbose)
  runview.py         flatten links.{kind} → ordered events; terminal-status set
  connect.py         install the skill into a chat runtime (+ WSL hand-off)
  autostart.py       windowless logon autostart (schtasks / systemd --user / launchd)
  bridge.py          loopback HTTP server (/login, /login/remote/*, /devices,
                     /devices/public, /devices/requests, /device/{select,pair,remove,
                     ask,decide,visibility}, /research, /updates, /logs/{runs,send,
                     bundle,agent-log}, /version, /agent-install, /install-backend, …)
  web/login.html     Firebase Web SDK Google sign-in (TOTP MFA aware)
  skill/             the chat-runtime bundle — SKILL.md + scripts/sr.py (the chat client)
                     + sr_attention_poll.py (the streaming watchdog) + sr_update_notice.py
  cli.py             the `agent` command
```
