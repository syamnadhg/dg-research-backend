---
name: super-research
description: >-
  Run Super Research from chat. Use when the user asks to research a topic, run
  a deep-research report, generate a brief / podcast / audio overview / video on
  a subject, to check, track, list, skip, or cancel a Super Research run, or to
  get started with Super Research — or types /sr-login, /sr-logout, /sr-device,
  /sr-research, /sr-status, /sr-podcast, /sr-skip, /sr-cancel, or /superresearch.
  Drives the user's own Super Research account (research-only) on their existing
  devices; every run shows up in their web app as a normal chat.
---

# Super Research (from chat)

You operate the user's **own** Super Research account through a local bridge.
You can **run, track, and cancel** research; you can **never** control devices
(add / remove / pair / share) — that stays owner-only in the web app.

All actions go through the bundled client. Run it and relay its output to the
user (it prints chat-ready text):

```
python scripts/sr.py <command> [args]
```

If a command prints `✗ bridge unreachable … is `agent serve` running?`, tell the
user the host bridge isn't running and stop.

> **The chat commands are `sr-` prefixed** (and the welcome is `/superresearch`)
> so they never collide with the runtime's own `/login`, `/status`, `/help`, etc.
> The runtime owns the un-prefixed names; this skill only ever sees the `sr-`
> ones. If a user types a bare `/login` or `/research`, point them at the
> `/sr-` form (or `/superresearch` for the full list).

## `/superresearch` — start here

When the user types `/superresearch` (or asks what Super Research is / how to
start), greet them and show what they can do. First run `sr.py status-account`:

- **Not signed in** → welcome them and say the first step is **`/sr-login`**
  (sign in once on their phone). Then list the commands below.
- **Signed in** → greet them by their account email, then list the commands and
  point them at `/sr-research <topic>` to start (and `/sr-device` to choose
  where it runs).

The controls (all **research-only** — Super Research can never add, remove,
pair, or share devices; that stays in the web app):

- **`/sr-login`** — sign in (approve on your phone)
- **`/sr-logout`** — sign out
- **`/sr-device`** — list devices · `/sr-device use <id>` to switch
- **`/sr-research <topic>`** — start a run
- **`/sr-status [id]`** — a run's progress + links
- **`/sr-podcast [id]`** — get a run's audio as a voice message
- **`/sr-skip <id> <phases>`** — skip Brief / Podcast / Video / Report
- **`/sr-cancel <id>`** — cancel a run
- **`/superresearch`** — this help

## Slash commands → what to run

| User says | Run | Then |
|---|---|---|
| `/sr-login` | `sr.py login` | Relay the sign-in link. Tell them to open it, sign in on their phone, and tap **Approve & connect** — then run `sr.py login-wait` (repeat every few seconds while it says "still waiting"). |
| `/sr-logout` | `sr.py logout` | Relay. |
| `/sr-device` (list) | `sr.py devices` | Relay the list. To switch: `sr.py device-use <id>`. |
| `/sr-device use <id>` | `sr.py device-use <id>` | Relay. |
| `/sr-research <topic>` | `sr.py research "<topic>"` | Relay the run id, then **stream** (below). |
| `/sr-status [id]` | `sr.py status [id]` | Relay status + links. |
| `/sr-podcast [id]` | `sr.py podcast [id]` | It prints a local **file path**. **Attach that file as a native audio / voice message** titled with the run's title — do **not** paste the path (or any URL) into chat. No id = the most recent run. If it says the audio isn't ready, relay that and try again later. |
| `/sr-skip <id> <phases>` | `sr.py skip <id> <phases>` | Offer the skippable phases (Brief=1, Podcast=3, Video=4, Report=5), then run it. Takes effect when each phase is reached. |
| `/sr-cancel <id>` | `sr.py cancel <id>` | **Confirm with the user first**, then run it. |
| `/superresearch` | `sr.py status-account` | Welcome the user + list the commands (see **start here** above): if "Not signed in", the first step is `/sr-login`; otherwise greet them by email. |

`/sr-research` accepts `--no-video` and `--no-email` to skip those phases, and
`--device <id>` to override the chosen device.

## First-time setup

If `sr.py status-account` says "Not signed in", guide the user through `/sr-login`
before running research. They pick a device with `/sr-device` (skipped
automatically if they have exactly one).

## Streaming a run's progress

After `/sr-research`, the run executes on the device and writes links phase by
phase. Stream them to the user as they appear — do **not** poll in a tight loop
yourself; rely on the runtime's periodic wake-up (cron). On each wake-up:

1. Run `sr.py --json updates --active`.
2. For each run, post any link you have **not** posted before (dedup by the
   run id + link kind — never repeat a link you already sent).
3. When a run's status becomes `completed` (or `stopped` / `error`), post the
   final state and stop streaming that run.

Links arrive in this order: Brief → ChatGPT / Gemini / Claude → NotebookLM +
Audio → YouTube → the final Doc.

## Safety

- Confirm before `/sr-cancel` (it stops a real run).
- Never ask for or handle passwords / tokens — sign-in happens on the user's
  phone via the link from `/sr-login`.
- You drive the user's own account only; you cannot reach anyone else's data.
