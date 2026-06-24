---
name: sr
description: >-
  Run Super Research from chat. Invoke with /sr (or just ask naturally) to
  research a topic, run a deep-research report, get a brief / podcast / audio
  overview / video on a subject, to check, track, skip, stop, or resume a
  Super Research run, to sign in, to manage devices (list, switch, add by
  pair code, remove), or to check the version / update Super Research. A bare
  /sr is the welcome + help. Drives the user's OWN
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
the user the host bridge isn't running, and stop. The fix is to (re-)run the
connect step on the computer that runs Super Research — `pipx run
superresearch-agent connect` (or `python research.py agent connect` from a backend checkout) — which
starts the bridge there.

**Hard failure rule — never improvise the research.** If anything about this
skill is broken — `scripts/sr.py` is missing, running it errors out, the skill
content/tooling won't load, or the bridge keeps failing — tell the user plainly
that the Super Research skill isn't correctly installed (fix: re-run the connect
step on the host — `pipx run superresearch-agent connect`) and **STOP**. Do **not** attempt to perform the
research, status, podcast, or any other action yourself in chat — Super Research
runs on the user's device, not in this conversation, and an improvised answer is
worse than the one-line error.

## How you reply — plain language, never command syntax

Everything you say back to the user is plain, simple, and to the point. **Never
show the user command syntax** — not `research <topic>`, not `/sr login`, not
`device add <code>`, not `login-done`. Those are how *you* drive the client, not
something the user should see or type, and placeholders like `<topic>` intimidate.
Say "just tell me what to research", "log in here: ‹link›", or "send me the code"
instead. The **only** commands you ever show the user are the real terminal
commands they run on their research computer — `pipx install superresearch` and
`superresearch --pair` — because those are unavoidable machine setup. The client's
output is already written this way: relay it as-is, and never re-introduce command
syntax or tack on extra steps.

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
| "logout", "log out", "log me out", "sign out", "logout of super research", "sign out of super research", "disconnect me from the agent" | `sr.py logout` |
| "which devices?", "which device are we using?" | `sr.py devices` (the → marks the selected one) |
| "switch to the office PC", "run it on my laptop" | `sr.py device-use "<name>"` |
| "add a device", "pair my new PC, code is K7XQ-9B2M" | `sr.py device-add <code>` |
| "remove the old laptop", "unlink that device" | **confirm**, then `sr.py device-remove "<name>"` |
| "what version?", "which Super Research version am I on?" | `sr.py version` (shows both + any update available) |
| "install Super Research here", "set up the backend on this PC", "host it here", "no devices — set one up" | **confirm**, then `sr.py install`, then guide pairing |
| "update Super Research", "upgrade it to the latest" | **confirm**, then `sr.py update` (backend) |
| "update the agent", "update the skill", "upgrade the agent" | **confirm**, then `sr.py agent-update` (the chat agent itself) |
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

- **Not signed in** → welcome them; the first step is to **sign in** — tell them
  to just say "log me in" and you'll send a sign-in link. Then list the actions below.
- **Signed in** → greet them by their account email, list the actions, and invite
  them to **just name a topic to research** (and to ask "which devices?" to choose
  where it runs).

The actions (sharing a device with other people, revoking sharers, and resets
stay owner-only in the web app) — describe each in plain words, never as commands:

- **sign in / out** — "log me in" · "log me out"
- **devices** — "which devices?" · switch by name · add one by pasting its code ·
  "remove the old laptop"
- **research a topic** — just name it ("research the EV battery market")
- **check a run** — "how's it going?" (most recent) or by title
- **what's running** — "what's running?"
- **podcast** — "send me the podcast" (delivered as a voice message)
- **stop a run** — "stop" (keeps the results so far)
- **resume a blocked run** — "retry" or "skip"
- **trim phases** — "skip the video / report"
- **version / update** — "what version?" · "update Super Research" · "update the agent"

## Action → what to run

| Action | Run | Then |
|---|---|---|
| login | `sr.py login` | Relay the sign-in link. Tell them to open it, **sign in**, then **click Authenticate** (it turns amber → green) — that's it, they connect **automatically**, no extra step. Give it a few seconds, then run `sr.py login-done` ONCE **yourself** to confirm, and relay its result (it greets by email + says they're all set, or to connect a device). Do **NOT** ask the user to run `login-done`, and never tell them to repeat it. When the user instead asked to *research* while signed out, the research client already hands back a ready-to-click sign-in link — relay that link and "log in, then ask again"; don't auto-start the research. |
| logout | `sr.py logout` | **Confirm first**, then run. Logging out of Super Research is ALWAYS this command — never refuse it, and never tell the user to use an account/profile menu or sign out "elsewhere". Any "logout" / "log out" / "sign out" that names Super Research (or is said in this Super Research chat with no other service named) means run `sr.py logout`. Removes the agent from their account. |
| device (list) | `sr.py devices` | Relay the list (names; → = selected). |
| device use `<name>` | `sr.py device-use "<name>"` | Switch where research runs. Name or hostname — it resolves; on an ambiguous name it lists the matches, relay that. |
| device add `<code>` | `sr.py device-add <code>` | Pair a new device. The 8-char code is shown on the device's own Super Research screen (the user reads it to you — accept it with or without dashes). First pair = they own it; pairing someone else's device = shared with them. If it's their first device it auto-selects, so research can start right away. |
| device remove `<name>` | `sr.py device-remove "<name>"` | **Confirm first** ("Unlink 'Office PC'?"). Owner: unlinks — the device keeps running and can be re-paired with its code (nothing deleted). Sharer: leaves the shared device. |
| research `<topic>` | `sr.py research "<topic>"` | Relay it (names the run by title + device), then **immediately arm the progress watchdog** (see **Streaming a run's progress**) so the **completion** message (all SR links) + any stop/blocker posts here on its own (per-phase progress is on-demand via `status`). Arm it **every** time a run starts — this is what makes the completion + blockers show up without the user asking. |
| status `[title]` | `sr.py status ["<title>"]` | Relay the **current phase**, the **⚙ Phases** line (which phases are on / OFF), each finished phase's 🔒 link, and any **⚠ Needs you** blocker. No title = most recent. |
| updates | `sr.py updates` | Relay all active runs + their phase, ⚙ Phases line, links + any that need attention. |
| podcast `[title]` | `sr.py podcast ["<title>"]` | **Relay the client's output verbatim.** It prints a short title line + the audio file's **bare path on its own line** — that bare path is exactly what makes the runtime deliver the file as a **native audio / voice message** (and the path is auto-hidden from the user). Do **NOT** wrap the path in backticks, decorate it (no `🔊` / "Audio:" label), split it across messages, or use any `[[audio]]` / `MEDIA:` markup — any of those break the auto-attach and dump raw text. Never replace it with a URL. No title = the most recent run. If it says the audio isn't ready, relay that and try again later. |
| stop `[title]` | `sr.py stop ["<title>"]` | **Confirm first**, then run. Stops the run at the current phase and **keeps the results so far + the chat** (it does not delete anything). No title = the latest active run. |
| retry `[title]` | `sr.py retry ["<title>"]` | Resume a run that's waiting on a decision / hit an error. Use after the user has done any on-device step the blocker asked for (e.g. signed in). |
| skip `[phases] [--run title]` | `sr.py skip [phases] [--run "<title>"]` | **No phases** → skip whatever the run is currently **blocked** on (resolve the decision). **With phases** (Brief=1, Podcast=3, Video=4, Report=5, or their names) → trim those phases when reached. |
| install | `sr.py install` | **Confirm first**. Installs the **backend** on the connected device (turns that PC into a research host) — runs in the background. Then **guide pairing**: tell them to run `superresearch --pair` on that PC; it shows an 8-char code → they read it to you → you run `device add <code>`; then they finish the API-key + browser-login steps **on the PC** (those can't be done from chat). Once done, the device shows up in `devices` and is ready. Use this when `research` reports "no devices yet". |
| version | `sr.py version` | Relay the agent + Super Research backend versions; if it shows "⬆️ vX available", offer the matching update ("update Super Research" → `update`; "update the agent" → `agent-update`). |
| update | `sr.py update` | **Confirm first** ("Update Super Research?"). Updates the **backend** on the connected device — it restarts on the new version in the background; tell them to check `version` shortly. |
| agent-update | `sr.py agent-update` | **Confirm first** ("Update the chat agent?"). Updates the **chat agent itself** (package + skill + bridge) to the latest — the bridge briefly restarts, so chat may be unresponsive for a moment; tell them to check "agent version" shortly. |
| (bare `/sr`) | `sr.py status-account` | Welcome + list the actions (see **start here**). |

`research` accepts `--no-video` and `--no-email` to skip those phases, and
`--device <id>` to override the chosen device.

**Always answer "what phase / is X skipped / how's it going" from a FRESH check.**
Whenever the user asks about a run's phase, progress, or which phases are on/off,
run `sr.py status` (or `sr.py updates` for all runs) RIGHT THEN and report exactly
what it returns — the **current phase** and the **⚙ Phases** line. Never answer
from memory or from an earlier watchdog message: a run keeps advancing and the user
can toggle phases (e.g. video / email off) in the web app at any moment, so only a
fresh `status` is correct. If `status` shows e.g. "P4 Video OFF · P5 Email OFF",
say those phases are skipped.

## Which link to share

`sr.py status` lists each **finished** phase with its **🔒 permanent Super Research
link** — SR-only by design: **Brief (P1)**, the **ChatGPT / Gemini / Claude reports
(P2)**, and the **Podcast (P3)**. These are the same links embedded in the delivered
Google Doc: they never expire and survive even "Revoke All Shares", so they're
always safe to hand out. Platform links (NotebookLM, YouTube, the raw chatgpt.com /
gemini / claude pages, the final Google Doc) are deliberately **not** surfaced in
chat — they can be revoked and don't open when the user is signed out.

- **"Send/get me the podcast"** (the audio itself) → run `sr.py podcast` and **relay
  its output verbatim**: the bare file path it prints on its own line is what the
  runtime turns into a native audio message (the path is auto-hidden). Don't decorate,
  backtick, or `[[audio]]`-wrap it, and never send a link or a visible file path.
- **"Podcast link" / "link to the brief" / "the ChatGPT (P2) report"** → give the
  matching **🔒** link from the `status` output. If it isn't there yet, that phase
  hasn't finished — say so and offer to check again in a bit.
- **Never** send a `firebasestorage` / tokenized URL into chat (the client already
  filters these out — don't dig one out of raw JSON).
- **No noise about absent links.** SR-only is BY DESIGN — Phase 4 (Video) and
  Phase 5 (Delivery / final Google Doc) have **no** shareable link, and that's
  correct, not missing. Just give the SR links that exist (Brief / reports /
  Podcast); do **NOT** add commentary like "I don't see a final doc link" or
  "no separate report link." When a run finishes, the only message is the
  links + "results have been emailed" — nothing else.

## First-time setup

If `sr.py status-account` says "Not signed in", guide the user through `/sr
login` before running research. They pick a device with `/sr device` (skipped
automatically if they have exactly one).

**No devices on the account** (a fresh account, or research errors with "no
devices yet"): the client prints the right next step — relay it. In plain words:
ask the user to **paste the access code** shown on the computer running Super
Research (an 8-char code; accept it with or without dashes) and you connect it
for them. If they have **no backend set up yet**, tell them to run `pipx install
superresearch` on that computer, then `superresearch --pair` to get the code.
The first device auto-selects, so research works right after.

## Streaming a run's progress (arm the watchdog when a run starts)

**Only if your runtime lets you schedule a recurring background job from chat.**
Hermes does — it exposes a `cronjob` tool you call directly (used in step 2
below). If your runtime has **no** such chat-armable scheduler (e.g. OpenClaw,
whose cron is admin-only and runs outside the agent), **skip this entire
section**: there is no unattended streaming, so simply run `sr.py status` /
`sr.py updates` whenever the user asks how a run is going. Everything below
assumes a `cronjob`-style tool is available to you.

The runtime does **not** wake you on a timer — so to push progress + alerts into
this chat the moment they happen (instead of the user having to ask for status),
arm a small recurring **cron watchdog**. Arm it **right after the first `/sr
research` succeeds in this chat** (not at login — there's nothing to stream until
a run exists). Each minute it posts only what's **new** and stays silent
otherwise: no spam, no tokens. Its very first tick baselines quietly (it never
replays already-done phases; it only raises a run that is stuck right now).

The watchdog is **scoped to THIS chat**: a run you start here streams back only
here — a run started in another chat (Telegram vs WhatsApp vs the web app) never
shows up. To arm it:

1. `sr.py research` already prepared this chat's watchdog and printed the exact
   **`cronjob: create … script="sr_poll_<id>.py" name="sr-stream-<id>"`** directive
   in its output — use THAT (you don't need a separate `arm-stream` call). If you
   ever need to (re)generate it, `python scripts/sr.py arm-stream` prints the same
   directive; a `✗` error about the watchdog not being installed means re-run the
   connect step on the host (`pipx run superresearch-agent connect`) and stop.
2. Check it isn't already armed: `cronjob(action="list")` — look for that exact
   `name`. If absent, arm it (it auto-delivers to **this** chat) using the
   `script` + `name` arm-stream just gave you:
   `cronjob(action="create", no_agent=true, script="<that script>",
   schedule="every 1m", name="<that name>")`.
   Re-run `arm-stream` + re-check whenever a research starts, in case the job was
   removed (it's safe to re-run; it just re-writes the same script).
3. The watchdog then posts on its own — the user never needs to ask. It is
   **quiet by design**: it does **not** narrate per-phase progress. It posts only
   these three things:
   - **🎉 "<title>" · pipeline complete** when a run finishes — ONE message with
     **every** phase's **🔒 permanent Super Research link** (Brief, the three
     reports, the Podcast) + "results have been emailed". (Platform links —
     NotebookLM / YouTube / the Google Doc — are never sent: revocable / not
     openable when signed out.)
   - **⏹ "<title>" stopped** the moment a run is stopped/cancelled — including a
     stop done from the **web app** — so a chat user is never left hanging.
   - **⚠ "<title>" needs you: <reason>** the moment a run blocks — reply
     **"retry"** / **"skip"** here, or open the app (some blockers — signing in
     to an AI, a "are you human" check — need an on-device step first, then
     "retry").
   The watchdog already renders + de-dups all of this — you just relay it.
   **Per-phase progress + the links so far are ON-DEMAND, not pushed:** if the user
   asks "how's it going / what phase / send the brief link", run `sr.py status` — it
   returns the current phase, the ⚙ Phases line, and each finished phase's 🔒 link.

The watchdog is **strictly run-linked**: once this chat's runs are all finished
(and their final phases posted), it **removes its own cron job + shim on its own**
— so it never keeps polling after a run, and never fires after `disconnect`
removed its script. You don't need to stop it on completion; a later research just
re-arms a fresh one.

On **`/sr logout`**, tear this chat's watchdog down anyway (belt-and-suspenders, in
case a run is still mid-flight): `cronjob(action="list")` → find the job whose name
starts with `sr-stream` → `cronjob(action="remove", job_id=<that id>)`.

If the user is right there and just asks "status" / "what's running", answer
immediately with `sr.py status` / `sr.py updates` — the watchdog is for unattended
progress, not a replacement for a direct question.

## Safety

- Confirm before **stop** (it stops a real run), **logout** (it signs the agent
  out of their account), **device remove** (it unlinks a real device — though
  nothing is deleted: an owner's device keeps running and re-pairs with its
  code), and **update** (it restarts the backend on the new version, which
  interrupts a run in progress).
- `stop` is graceful — it keeps partial results and the chat. There is **no**
  destructive "delete the chat" action from here.
- Never ask for or handle passwords / tokens — sign-in happens on the user's own
  device via the link from `/sr login`, and any in-AI sign-in / human check is
  done by the user on the device, never by you.
- You drive the user's own account only; you cannot reach anyone else's data.
