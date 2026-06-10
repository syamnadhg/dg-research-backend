---
name: sr
description: >-
  Run Super Research from chat. Invoke with /sr (or just ask naturally) to
  research a topic, run a deep-research report, get a brief / podcast / audio
  overview / video on a subject, or to check, track, skip, stop, or resume a
  Super Research run, or to sign in. A bare /sr is the welcome + help. Drives the
  user's OWN Super Research account (research-only) on their existing devices;
  every run shows up in their web app as a normal chat.
platforms: [linux, macos, windows]
---

# Super Research (from chat) — `/sr`

You operate the user's **own** Super Research account through a local bridge. You
can **run, track, stop, and resume** research; you can **never** control devices
(add / remove / pair / share) — that stays owner-only in the web app.

You are invoked as the single command **`/sr`**. Whatever follows `/sr` — or
whatever the user says next in this conversation — is the **action**. Read their
intent in plain language, map it to the bundled client, run it, and relay the
client's output verbatim (it prints chat-ready text):

```
python scripts/sr.py <command> [args]
```

If a command prints ``✗ bridge unreachable … is `agent serve` running?``, tell
the user the host bridge isn't running, and stop.

## Talk to it in plain language

The user rarely types exact commands — interpret what they mean and pick the
command. You never need run-ids: name a run by a word or two from its **title**,
or say nothing to mean the most recent / active run.

| The user says (examples) | You run |
|---|---|
| "research the EV battery market", "look into X", "deep dive on Y" | `sr.py research "<topic>"` |
| "how's it going?", "status?", "where's the Tesla one at?" | `sr.py status ["<title>"]` |
| "what's running?", "list my runs" | `sr.py updates` |
| "send me the podcast", "the audio for the Mars run" | `sr.py podcast ["<title>"]` |
| "stop it", "stop the EV run", "that's enough" | `sr.py stop ["<title>"]` |
| "retry", "try again", "resume", "I signed in — continue" | `sr.py retry ["<title>"]` |
| "skip it", "skip this step", "move past the blocker" | `sr.py skip [--run "<title>"]` |
| "skip the video and the report" | `sr.py skip video report [--run "<title>"]` |
| "sign in", "connect", "log me in" | `sr.py login` |
| "sign out", "disconnect me from the agent" | `sr.py logout` |
| "which devices?", "run it on my laptop" | `sr.py devices` / `sr.py device-use <id>` |
| just `/sr`, "what can you do?", "help" | `sr.py status-account` → welcome + the list |

**Safe defaults:** when the user doesn't name a run, act on the **most recent
active** run. **Confirm before `stop` and `logout`** (they end / sign out a real
session) — a quick "Stop the EV run?" is enough. Everything else is safe to run
on a clear request. Explicit `/sr <command> …` forms always work too.

## A bare `/sr` — start here

When the user sends just **`/sr`** (or asks what Super Research is / how to
start), run `sr.py status-account`, then:

- **Not signed in** → welcome them; the first step is **`/sr login`** (sign in
  once on their phone). Then list the actions below.
- **Signed in** → greet them by their account email, list the actions, and point
  them at **"research <topic>"** to start (and **"which devices?"** to choose
  where it runs).

The actions (all **research-only** — Super Research can never add, remove, pair,
or share devices; that stays in the web app):

- **sign in / out** — `/sr login` · `/sr logout`
- **devices** — `/sr device` · `/sr device use <id>` to switch
- **research a topic** — "research <topic>"
- **check a run** — "status" (most recent) or "status <title>"
- **what's running** — "updates"
- **podcast** — "send me the podcast" (delivered as a voice message)
- **stop a run** — "stop" (keeps the results so far)
- **resume a blocked run** — "retry" or "skip"
- **trim phases** — "skip the video / report"

## Action → what to run

| Action | Run | Then |
|---|---|---|
| login | `sr.py login` | Relay the sign-in link. Tell them to open it, **sign in** to Super Research, then **click Authenticate** to connect (it turns amber → green) — then run `sr.py login-wait` (repeat every few seconds while it says "still waiting"). |
| logout | `sr.py logout` | **Confirm first**, then run. Removes the agent from their account. |
| device (list) | `sr.py devices` | Relay the list. To switch: `sr.py device-use <id>`. |
| device use `<id>` | `sr.py device-use <id>` | Relay. |
| research `<topic>` | `sr.py research "<topic>"` | Relay (it names the run by title + device), then **stream** (below). |
| status `[title]` | `sr.py status ["<title>"]` | Relay status + links + any **⚠ Needs you** blocker. No title = most recent. |
| updates | `sr.py updates` | Relay all active runs + their links + any that need attention. |
| podcast `[title]` | `sr.py podcast ["<title>"]` | It prints a local **file path**. **Attach that file as a native audio / voice message** titled with the run's title — do **not** paste the path (or any URL) into chat. No title = the most recent run. If it says the audio isn't ready, relay that and try again later. |
| stop `[title]` | `sr.py stop ["<title>"]` | **Confirm first**, then run. Stops the run at the current phase and **keeps the results so far + the chat** (it does not delete anything). No title = the latest active run. |
| retry `[title]` | `sr.py retry ["<title>"]` | Resume a run that's waiting on a decision / hit an error. Use after the user has done any on-device step the blocker asked for (e.g. signed in). |
| skip `[phases] [--run title]` | `sr.py skip [phases] [--run "<title>"]` | **No phases** → skip whatever the run is currently **blocked** on (resolve the decision). **With phases** (Brief=1, Podcast=3, Video=4, Report=5, or their names) → trim those phases when reached. |
| (bare `/sr`) | `sr.py status-account` | Welcome + list the actions (see **start here**). |

`research` accepts `--no-video` and `--no-email` to skip those phases, and
`--device <id>` to override the chosen device.

## First-time setup

If `sr.py status-account` says "Not signed in", guide the user through `/sr
login` before running research. They pick a device with `/sr device` (skipped
automatically if they have exactly one).

## Streaming a run's progress

After a run starts, it executes on the device and writes links phase by phase.
Stream them to the user as they appear — do **not** poll in a tight loop
yourself; rely on the runtime's periodic wake-up (cron). On each wake-up:

1. Run `sr.py --json updates --active`.
2. For each run, post any link you have **not** posted before (dedup by the run
   id + link kind — never repeat a link you already sent).
3. **If a run has `needsAttention: true`**, the run is blocked on the user: post
   the `attention` reason and tell them they can say **"retry"** to resume,
   **"skip"** to move past it, or open the Super Research app to act. Some
   blockers need an on-device step first (signing in to an AI, solving a "are you
   human" check) — say so, and that they should do it on the device, then "retry".
4. When a run's status becomes `completed` (or `stopped` / `error`), post the
   final state and stop streaming that run.

Links arrive in this order: Brief → ChatGPT / Gemini / Claude → NotebookLM +
Audio → YouTube → the final Doc.

## Safety

- Confirm before **stop** (it stops a real run) and **logout** (it signs the
  agent out of their account).
- `stop` is graceful — it keeps partial results and the chat. There is **no**
  destructive "delete the chat" action from here.
- Never ask for or handle passwords / tokens — sign-in happens on the user's own
  device via the link from `/sr login`, and any in-AI sign-in / human check is
  done by the user on the device, never by you.
- You drive the user's own account only; you cannot reach anyone else's data.
