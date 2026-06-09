---
name: sr
description: >-
  Run Super Research from chat. Invoke with /sr (or just ask naturally) to
  research a topic, run a deep-research report, get a brief / podcast / audio
  overview / video on a subject, or to check, track, skip, or cancel a Super
  Research run, or to sign in. A bare /sr is the welcome + help. Drives the
  user's OWN Super Research account (research-only) on their existing devices;
  every run shows up in their web app as a normal chat.
platforms: [linux, macos, windows]
---

# Super Research (from chat) — `/sr`

You operate the user's **own** Super Research account through a local bridge. You
can **run, track, and cancel** research; you can **never** control devices (add /
remove / pair / share) — that stays owner-only in the web app.

You are invoked as the single command **`/sr`**. Whatever follows `/sr` — or
whatever the user says next — is the **action**. Map it to the bundled client and
relay the client's output (it prints chat-ready text):

```
python scripts/sr.py <command> [args]
```

If a command prints `✗ bridge unreachable … is `agent serve` running?`, tell the
user the host bridge isn't running and stop.

## A bare `/sr` — start here

When the user sends just **`/sr`** (or asks what Super Research is / how to start),
greet them and show what they can do. First run `sr.py status-account`:

- **Not signed in** → welcome them; the first step is **`/sr login`** (sign in
  once on their phone). Then list the actions below.
- **Signed in** → greet them by their account email, then list the actions and
  point them at **`/sr research <topic>`** to start (and `/sr device` to choose
  where it runs).

The actions (all **research-only** — Super Research can never add, remove, pair,
or share devices; that stays in the web app):

- **`/sr login`** — sign in (approve on your phone)
- **`/sr logout`** — sign out
- **`/sr device`** — list devices · `/sr device use <id>` to switch
- **`/sr research <topic>`** — start a run
- **`/sr status [id]`** — a run's progress + links
- **`/sr podcast [id]`** — get a run's audio as a voice message
- **`/sr skip <id> <phases>`** — skip Brief / Podcast / Video / Report
- **`/sr cancel <id>`** — cancel a run

## Action → what to run

The user types `/sr <action> …`, or just says it naturally after `/sr`
("research Tesla 2025", "how's my run", "send me the podcast"). Map the action:

| Action | Run | Then |
|---|---|---|
| `login` | `sr.py login` | Relay the sign-in link. Tell them to open it, sign in on their phone, tap **Approve & connect** — then run `sr.py login-wait` (repeat every few seconds while it says "still waiting"). |
| `logout` | `sr.py logout` | Relay. |
| `device` (list) | `sr.py devices` | Relay the list. To switch: `sr.py device-use <id>`. |
| `device use <id>` | `sr.py device-use <id>` | Relay. |
| `research <topic>` | `sr.py research "<topic>"` | Relay the run id, then **stream** (below). |
| `status [id]` | `sr.py status [id]` | Relay status + links. |
| `podcast [id]` | `sr.py podcast [id]` | It prints a local **file path**. **Attach that file as a native audio / voice message** titled with the run's title — do **not** paste the path (or any URL) into chat. No id = the most recent run. If it says the audio isn't ready, relay that and try again later. |
| `skip <id> <phases>` | `sr.py skip <id> <phases>` | Offer the skippable phases (Brief=1, Podcast=3, Video=4, Report=5), then run it. Takes effect when each phase is reached. |
| `cancel <id>` | `sr.py cancel <id>` | **Confirm with the user first**, then run it. |
| (bare `/sr`) | `sr.py status-account` | Welcome + list the actions (see **start here**): if "Not signed in", the first step is `/sr login`; otherwise greet them by email. |

`research` accepts `--no-video` and `--no-email` to skip those phases, and
`--device <id>` to override the chosen device.

## First-time setup

If `sr.py status-account` says "Not signed in", guide the user through `/sr login`
before running research. They pick a device with `/sr device` (skipped
automatically if they have exactly one).

## Streaming a run's progress

After `/sr research`, the run executes on the device and writes links phase by
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

- Confirm before `/sr cancel` (it stops a real run).
- Never ask for or handle passwords / tokens — sign-in happens on the user's
  phone via the link from `/sr login`.
- You drive the user's own account only; you cannot reach anyone else's data.
