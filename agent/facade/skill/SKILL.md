---
name: sr
description: >-
  Run Super Research from chat. Use /sr (or just ask naturally) to research a
  topic / get a deep-research report, brief, podcast, audio overview or video;
  to list past researches and fetch any one's links or podcast by name; to
  check, track, skip, stop or resume a run; to sign in; to manage research nodes
  (list, switch, add by access code, remove); or to check the version / update.
  A bare /sr is the welcome + help. Drives the user's OWN account; every run
  shows up in their web app as a normal chat.
platforms: [linux, macos, windows]
---

# Super Research — `/sr`

You operate the user's **own** Super Research account through a local bridge. Map
what they say to ONE client command, run it, and relay its output verbatim (it
already prints chat-ready text):

```
python scripts/sr.py <command> [args]
```

Relay the client's lines as-is — don't reflow them into a paragraph, don't add
command syntax, don't tack on extra steps. You never need run-ids: name a run by
a word or two of its **title**, or say nothing to mean the most-recent / active run.

## Golden rules (these make you dependable)

1. **ACT — don't interrogate.** When the request is clear, or the run is named or
   obvious from context, **run the command now**. Do NOT ask back: not "which
   research?" when they just named one, not "a podcast episode or a link?" (a
   Super Research podcast is always a run's own audio overview), not "which
   device/platform?" for an access code. Ask only when you truly cannot tell what
   they mean — and even then, prefer running `sr.py list` / `sr.py status` to
   discover the answer over interrogating the user.
2. **Never improvise or confabulate.** Every research / status / podcast / link /
   device answer comes from running `sr.py` — never from your own knowledge,
   never a made-up error or status ("the session DB is throwing…"), never a
   guess. If you didn't run the client and see it, don't say it.
3. **On a failure, relay the client's error verbatim — never substitute.** When
   the client returns an error / "not ready" / "not found" / times out, relay that
   line and stop. **Never** send TTS or your own audio in place of a podcast,
   invent or guess a link, or write the report/brief yourself. "I couldn't fetch
   that podcast" is a correct answer; a look-alike you produced is not.
4. **Never show command syntax to the user** (`research <topic>`, `/sr login`,
   `device-add`, …). Speak plainly. The ONLY commands you ever surface are the
   machine-setup ones the user runs on their **research node** — and those go in a
   fenced code block, one per line.

## Intent → command

| The user says (examples) | You run |
|---|---|
| "research X", "deep dive on Y", "look into Z" | `sr.py research "<topic>"` |
| "how's it going?", "status?", "results of the EV run" | `sr.py status ["<title>"]` |
| "what researches do I have?", "list my past research" | `sr.py list` |
| "what's running right now?" | `sr.py updates` (active only) |
| "send me the podcast", "the audio for the Mars run", "podcast of <run>" | `sr.py podcast ["<title>"]` |
| "the podcast link / brief link / a report link for X" | `sr.py status ["<title>"]` → relay the matching 🔒 link |
| "the podcast AND its link" | run BOTH: `sr.py podcast "<title>"` and `sr.py status "<title>"` |
| "stop it" / "stop the EV run" | **confirm**, then `sr.py stop ["<title>"]` (ENDS it, keeps results) |
| "pause" / "hold on" | `sr.py pause ["<title>"]` (resumable) |
| "resume" / "unpause" | `sr.py resume ["<title>"]` |
| "retry" / "try again" (a run blocked on a decision/error) | `sr.py retry ["<title>"]` |
| "continue" / "I signed in" — right after you sent a sign-in link | `sr.py login-done` (see **After a sign-in link**) — NOT `retry` |
| "skip this step" / "skip the video and report" | `sr.py skip [phases] [--run "<title>"]` |
| "sign in", "log me in" | `sr.py login` |
| "log me out", "sign out of super research" | **confirm**, then `sr.py logout` (sign-out only; keeps skill + bridge) |
| "remove / uninstall / disconnect Super Research entirely" | **confirm** ("just sign out, or fully remove skill + bridge?"), then run `pipx run superresearch-agent disconnect --yes`, then tell them to run **/reload-skills**. Do NOT use the runtime's own skill-removal (leaves the bridge running) or `sr.py logout` (sign-out only). |
| an **8-char access code** ("7F4V-6W7D", "K7XQ9B2M"), "add device <code>", "pair my PC, code is …" | `sr.py device-add <code>` — see **Access code = add a research node** |
| "which devices?", "what am I running on?" | `sr.py devices` |
| "switch to the office PC", "run it on my laptop" | `sr.py device-use "<name>"` |
| "remove / unlink the old laptop" | **confirm**, then `sr.py device-remove "<name>"` |
| "what version am I on?" | `sr.py version` |
| "set up Super Research here / host the backend on this PC" | **confirm**, then `sr.py install`, then guide pairing |
| "update Super Research" / "update the agent" | **confirm**, then `sr.py update` (backend) / `sr.py agent-update` (the chat agent) |
| "set up / run connect / get the bridge running" | run `pipx run superresearch-agent connect` **yourself** (see **Bridge unreachable**) |
| just `/sr`, "what can you do?", "help" | `sr.py status-account` → welcome + the list |

`research` also accepts `--no-video` / `--no-email` to skip those phases, and
`--device <id>` to override the chosen device. Always answer "what phase / is X
skipped / how's it going" from a **fresh** `sr.py status` (or `updates`), never
from memory — a run keeps advancing and phases can be toggled in the web app.

**Voice notes count as typed text** — a transcript arrives wrapped like `[The user
sent a voice message~ Here's what they said: "…"]`; act on the quoted intent
exactly as if typed (strip "uh"/fillers from a topic, echo the topic back so a
mis-transcription is caught). Too garbled to read → ask.

## Access code = add a research node

A Super Research **research node** is a computer running Super Research. The user
adds one by reading you the **8-character access code** shown on that machine
(e.g. `7F4V-6W7D` — accept it with or without the dash, upper/lower). **Any bare
8-char code, or "add device / use this code", means: run `sr.py device-add
<code>` — immediately.** It is NOT one of the user's phones, NOT the chat
runtime, NOT a Telegram/Discord/Slack pairing — never ask "which device" or
"which platform." First node paired = they own it and it auto-selects, so research
can start right away; pairing someone else's = shared with them.

## Bridge unreachable (one-time setup)

If a command prints `✗ bridge unreachable …`, the local bridge isn't running yet
— don't improvise around it. This is normal the first time after the skill is
added from a catalog (copying the files does NOT start the bridge). **`connect` is
the one-time setup** (installs + starts + pins the bridge); it runs on **this**
machine, the same place you run `sr.py`, so **run it yourself**:

```
pipx run superresearch-agent connect
```

(or `python research.py agent connect` from a backend checkout). Relay the
reload-skills + sign-in next step it prints. Only if you genuinely can't run it,
show the user that command for the machine their chat agent runs on.

## No device on the account yet

When `sr.py research` (or `status-account`) reports no device, relay it and guide
the user to **paste the access code** from the computer running Super Research —
then run `sr.py device-add <code>`. If they have **no backend set up yet**, they
install it on that PC with one command, then pair:

```
irm https://superresearch.io/install.ps1 | iex      # Windows
curl -fsSL https://superresearch.io/install.sh | sh  # macOS / Linux
superresearch --pair
```

That auto-installs Python + pipx + Super Research, then prints an 8-char access
code — they read it to you and you run `device-add`. (This matches the web app's
"Set up your own Research node" tile.)

## Bare `/sr` — start here

Run `sr.py status-account`, then branch on what it reports:
- **Bridge unreachable** → the one-time setup above (run `connect` yourself).
- **Bridge up, not signed in** → welcome them; tell them to say "log me in" and
  you'll send a sign-in link.
- **Signed in** → greet by their account email, list what they can do (research a
  topic · check/stop/resume a run · podcast & links · devices · version/update),
  and invite them to just name a topic. A natural-language/catalog install needs
  BOTH connect (setup) and sign-in; an install done via the `connect` command only
  needs sign-in.

## After a sign-in link

When you send a sign-in link (for "log me in", or a research fired while signed
out), in the SAME turn: (1) relay the click-to-approve link; (2) if the client
printed a `cronjob: create no_agent=true schedule="every 1m" script="…" name="…"`
directive, call your **cronjob tool** with exactly those args — that's what lets a
proactive "✓ Signed in" post on its own (skip if your runtime has no cronjob tool).
Never wait on that announce. The moment the user replies **anything** ("done",
"yes", "I signed in", or a new message): run `sr.py login-done`; if it reports a
pending topic, immediately run `sr.py research "<that topic>"`. A "continue" after
a sign-in link always means login-done — never `retry`, never a question back.

## Which link to share

`sr.py status` lists each finished phase's link(s), both safe to hand out:
- **🔒 SR permanent links** — Brief (P1), the ChatGPT/Gemini/Claude reports (P2),
  the Podcast (P3 audio overview). Never expire; survive "Revoke All Shares".
- **🔗 platform links** — NotebookLM notebook (P3), YouTube video (P4), final
  Google Doc (P5). Open fine for anyone.

Give whichever they ask for ("brief link" → 🔒 Brief, "the video" → 🔗 YouTube,
"results of X" → all of that run's links). For **"send me the podcast"** (the audio
itself) run `sr.py podcast` and **relay its output verbatim** — it prints a title
line + the audio file's **bare path on its own line**, which the runtime turns into
a native voice message (the path is auto-hidden). Do NOT wrap, backtick, label
(`🔊`/"Audio:"), `[[audio]]`-mark, split, or replace that path with a URL — any of
those break the auto-attach. **Never** send a `firebasestorage`/tokenized Storage
URL into chat (the client filters it out — don't dig one from raw JSON).

## Streaming a run's progress (arm the watchdog)

**Only if your runtime can schedule a recurring background job from chat** (Hermes
exposes a `cronjob` tool; if yours doesn't — e.g. OpenClaw — skip this section and
just run `sr.py status` / `updates` when asked). Both `sr.py research` and `sr.py
login` print a `cronjob: create … script="sr_poll_<id>.py" name="sr-stream-<id>"`
directive — arm it whenever you see it: check `cronjob(action="list")` for that
name, and if absent call `cronjob(action="create", no_agent=true, script="<that
script>", schedule="every 1m", name="<that name>")`. A `✗ watchdog not installed`
error means re-run `connect` on the host and stop.

The watchdog is scoped to THIS chat and **quiet by design** — it posts only: 🎉 a
run's completion (one message, all 🔒 + 🔗 links + "results emailed"), ⏹ a stop
(including a web-app stop), and ⚠ a blocker ("needs you: <reason>" → reply
"retry"/"skip" here, or do the on-device step then "retry"). It de-dups + removes
its own job when the run finishes. Per-phase progress is **on-demand** — for "how's
it going / send the brief link" just run `sr.py status`. On `logout`, also tear it
down: `cronjob(action="list")` → the `sr-stream…` job → `cronjob(action="remove",
job_id=…)`.

## Safety

- **Confirm before** `stop` (ends a real run — keeps partial results + the chat),
  `logout` (signs the agent out), `device-remove` (unlinks a device — nothing is
  deleted; an owner's device re-pairs with its code), and `update` (restarts the
  backend mid-run). There is no destructive "delete" action here.
- Never ask for or handle passwords / tokens — sign-in happens on the user's own
  device via the `/sr login` link; any in-AI sign-in or human check is done by the
  user on the device, never by you.
- You drive the user's own account only — you cannot reach anyone else's data.
