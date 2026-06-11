---
name: sr
description: >-
  Run Super Research from chat. Invoke with /sr (or just ask naturally) to
  research a topic, run a deep-research report, get a brief / podcast / audio
  overview / video on a subject, to check, track, skip, stop, or resume a
  Super Research run, to sign in, or to manage devices (list, switch, add by
  pair code, remove). A bare /sr is the welcome + help. Drives the user's OWN
  Super Research account; every run shows up in their web app as a normal chat.
platforms: [linux, macos, windows]
---

# Super Research (from chat) — `/sr`

You operate the user's **own** Super Research account through a local bridge. You
can **run, track, stop, and resume** research, and manage the account's
**devices**: list, switch, **add by pair code** (the code shown on the device's
own screen — possession of the code is the authorization), and **remove/unlink**
(confirm first). Sharing a device with OTHER people, revoking sharers, and
resetting a device stay owner-only in the web app.

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
| "podcast **link**", "link to the brief / ChatGPT doc" | `sr.py status ["<title>"]` → share the 🔒 permanent link (see **Which link to share**) |
| "stop it", "stop the EV run", "that's enough" | `sr.py stop ["<title>"]` |
| "retry", "try again", "resume", "I signed in — continue" | `sr.py retry ["<title>"]` |
| "skip it", "skip this step", "move past the blocker" | `sr.py skip [--run "<title>"]` |
| "skip the video and the report" | `sr.py skip video report [--run "<title>"]` |
| "sign in", "connect", "log me in" | `sr.py login` |
| "sign out", "disconnect me from the agent" | `sr.py logout` |
| "which devices?", "which device are we using?" | `sr.py devices` (the → marks the selected one) |
| "switch to the office PC", "run it on my laptop" | `sr.py device-use "<name>"` |
| "add a device", "pair my new PC, code is K7XQ-9B2M" | `sr.py device-add <code>` |
| "remove the old laptop", "unlink that device" | **confirm**, then `sr.py device-remove "<name>"` |
| just `/sr`, "what can you do?", "help" | `sr.py status-account` → welcome + the list |

**Safe defaults:** when the user doesn't name a run, act on the **most recent
active** run. **Confirm before `stop`, `logout`, and `device-remove`** (they end
/ sign out / unlink something real) — a quick "Stop the EV run?" / "Unlink
'Office PC'?" is enough. Everything else is safe to run on a clear request.
Devices are named by their **name** (or hostname) — never make the user type an
id. Explicit `/sr <command> …` forms always work too.

**Voice messages count as typed text.** A voice note reaches you transcribed,
wrapped like `[The user sent a voice message~ Here's what they said: "…"]` —
treat the quoted transcript exactly as if the user typed it: extract the intent
from the table above and act ("do a super research on the EV battery market"
spoken aloud starts that run, same as typed). Strip obvious speech artifacts
("uh", fillers, trailing punctuation) from a research topic but keep its
substance, and echo the topic back in your confirmation so the user can catch a
mis-transcription. If the transcript is too garbled to extract a clear topic or
action, ask — don't guess. The same stop/logout confirmation rule applies.

## A bare `/sr` — start here

When the user sends just **`/sr`** (or asks what Super Research is / how to
start), run `sr.py status-account`, then:

- **Not signed in** → welcome them; the first step is **`/sr login`** (sign in
  once on their phone). Then list the actions below.
- **Signed in** → greet them by their account email, list the actions, and point
  them at **"research <topic>"** to start (and **"which devices?"** to choose
  where it runs).

The actions (sharing a device with other people, revoking sharers, and resets
stay owner-only in the web app):

- **sign in / out** — `/sr login` · `/sr logout`
- **devices** — "which devices?" · switch by name · "add a device" (pair code) ·
  "remove <name>"
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
| device (list) | `sr.py devices` | Relay the list (names; → = selected). |
| device use `<name>` | `sr.py device-use "<name>"` | Switch where research runs. Name or hostname — it resolves; on an ambiguous name it lists the matches, relay that. |
| device add `<code>` | `sr.py device-add <code>` | Pair a new device. The 8-char code is shown on the device's own Super Research screen (the user reads it to you — accept it with or without dashes). First pair = they own it; pairing someone else's device = shared with them. If it's their first device it auto-selects, so research can start right away. |
| device remove `<name>` | `sr.py device-remove "<name>"` | **Confirm first** ("Unlink 'Office PC'?"). Owner: unlinks — the device keeps running and can be re-paired with its code (nothing deleted). Sharer: leaves the shared device. |
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

## Which link to share

`sr.py status` prints two groups of links. Pick by what the user asked for:

- **"Send/get me the podcast"** (the audio itself) → run `sr.py podcast` and
  attach the file as a **native audio / voice message** — never a link, never a
  file path pasted as text.
- **"Podcast link" / "link to the brief" / "the ChatGPT (P2) doc" / "share the
  report"** → give the matching **🔒 permanent link** from the "Permanent links"
  block (`https://…/shared/doc/…` or `/shared/podcast/…`). These are the same
  Super Research links embedded in the delivered Google Doc — they never expire
  and survive even "Revoke All Shares", so they're always safe to hand out.
  (Brief = the P1 doc; ChatGPT / Gemini / Claude reports = the P2 docs.)
- The plain 🔗 links (Google Doc brief, chatgpt.com / gemini / claude share
  pages, NotebookLM, YouTube, the final Doc) are live **progress** links — fine
  to relay as the run streams, but when the user asks for a link *to keep or
  share*, prefer the 🔒 permanent one. If no permanent link exists yet (the run
  hasn't delivered, or an older run), fall back to the plain link and say so.
- **Never** send a `firebasestorage` / tokenized URL into chat (the client
  already filters these out — don't dig one out of raw JSON).

## First-time setup

If `sr.py status-account` says "Not signed in", guide the user through `/sr
login` before running research. They pick a device with `/sr device` (skipped
automatically if they have exactly one).

**No devices on the account** (a fresh account, or research errors with "no
devices yet"): walk them through adding one — Super Research must be installed
and running on a computer; its screen shows an 8-char **pair code**; they read
it to you and you run `sr.py device-add <code>`. It auto-selects as their first
device, so "research <topic>" works immediately after.

## Streaming a run's progress (arm the watchdog at sign-in)

The runtime does **not** wake you on a timer — so to push progress + alerts into
this chat the moment they happen (instead of the user having to ask for status),
arm a small recurring **cron watchdog** **right after a successful `/sr login`**.
It covers **every** run on the account — including ones started from the web app
— and runs a bundled script that, each minute, posts only what's **new** and
stays silent otherwise: no spam, no tokens. Its very first tick baselines
quietly (it never replays old history into the chat; it only raises a run that
is stuck right now).

1. Check it isn't already armed: `cronjob(action="list")` — look for a job named
   `sr-stream`.
2. If absent, arm it — it auto-delivers to **this** chat:
   `cronjob(action="create", no_agent=true, script="sr_attention_poll.py",
   schedule="every 1m", name="sr-stream")`.
   (`agent connect` already placed `sr_attention_poll.py` in the scripts dir. If
   create fails with a missing-script error, tell the user to re-run `agent
   connect` on the host.)
   Also re-check/arm whenever a research starts, in case sign-in happened
   elsewhere or the job was removed.
3. The watchdog then posts on its own — the user never needs to ask:
   - each new phase link as it lands (Brief → ChatGPT / Gemini / Claude →
     NotebookLM + Audio → YouTube → the final Doc),
   - **⚠ "<title>" needs you: <reason>** the moment a run blocks — the user can
     reply **"retry"** / **"skip"** right here, or open the app (some blockers —
     signing in to an AI, a "are you human" check — need an on-device step first,
     then "retry"),
   - the final state when a run finishes / stops / errors.

On **`/sr logout`**, tear the watchdog down: `cronjob(action="list")` → find
`sr-stream` → `cronjob(action="remove", job_id=<that id>)`.

If the user is right there and just asks "status" / "what's running", answer
immediately with `sr.py status` / `sr.py updates` — the watchdog is for unattended
progress, not a replacement for a direct question.

## Safety

- Confirm before **stop** (it stops a real run), **logout** (it signs the agent
  out of their account), and **device remove** (it unlinks a real device —
  though nothing is deleted: an owner's device keeps running and re-pairs with
  its code).
- `stop` is graceful — it keeps partial results and the chat. There is **no**
  destructive "delete the chat" action from here.
- Never ask for or handle passwords / tokens — sign-in happens on the user's own
  device via the link from `/sr login`, and any in-AI sign-in / human check is
  done by the user on the device, never by you.
- You drive the user's own account only; you cannot reach anyone else's data.
