---
name: sr
description: >-
  USE THIS SKILL for ANY request to research a topic, run a deep-research report,
  "do a Super Research", or deep-dive a subject — it runs the user's REAL
  multi-agent Super Research pipeline on their own device and posts the result in
  their web app. **NEVER answer a research or deep-dive request from your own
  knowledge or with web search — ALWAYS invoke this skill instead**, whether the
  user types /sr or just asks in plain language. Also use it to get a brief /
  podcast / audio overview / video on a subject; to list past researches and fetch
  any one's links or podcast by name; to check, track, skip, stop, or resume a run;
  to sign in; to manage research nodes (list, switch, add by access code, remove);
  and to check the version / update. A bare /sr is the welcome + help. Drives the
  user's OWN Super Research account; every run shows up in their web app as a chat.
platforms: [linux, macos, windows]
---

# Super Research — `/sr`

You operate the user's **own** Super Research account from chat through a local
bridge: **run, track, stop, and resume** research, manage research **nodes**
(list, switch, add by access code, remove), and fetch briefs / podcasts / links.
Every run also shows up in their web app as a normal chat. You drive everything
with one client — it prints chat-ready text, so relay it **verbatim** (don't
reflow it into a paragraph, re-introduce command syntax, or tack on extra steps):

```
python scripts/sr.py <command> [args]
```

You never need run-ids: name a run by a word or two from its **title**, or say
nothing to mean the most-recent / active run.

**IMPORTANT — INSTRUCTIONS FOR AI AGENTS:**

- **Run the client; never improvise. HARD RULE — never improvise the research,
  ever.** A "research X" / "Super Research on X" / "deep dive on Y" request is
  ALWAYS satisfied by running `sr.py research "<topic>"` — **never** by answering
  from your own knowledge, not even a quick summary, not even a few bullet points,
  and **not even when you easily could**. The only thing you may show for a
  research request is what the client prints — Super Research runs on the user's
  device, not in this chat. This holds in EVERY case: **working normally** (relay
  the run the client started) · **no device on the account** (`sr.py research`
  does NOT fail silently — it returns the pair-a-device step; relay it and walk
  them through pairing) · **skill genuinely broken** (`scripts/sr.py` missing / it
  errors / the bridge keeps failing → tell the user the skill isn't correctly
  installed, fix by re-running `connect`, and **STOP**). The same rule applies to
  status / podcast / list / links / devices: run the client, relay its output — do
  not perform any of it yourself in chat.
- **On a FAILURE, relay the client's error verbatim — never substitute.** When the
  client returns an error, a "not ready / not found", or times out (a podcast, a
  link, a status, the list — anything), relay that message as-is and stop. **Never**
  generate or send TTS / your own audio in place of a podcast, invent or guess a
  link, or write the report or brief yourself. The user asked for the Super Research
  artifact specifically — they get the real one or the client's plain error, never
  a look-alike you produced. "I couldn't fetch that podcast" is correct; a 2-minute
  voice note you synthesized is not.
- **ACT — don't interrogate.** When the request is clear, or the run is named or
  obvious from context, run the command **now**. Don't ask "which research?" when
  they just named one, "a podcast episode or a link?" (a Super Research podcast is
  always a run's own audio overview), or "which device/platform?" for an access
  code. Ask only when you truly cannot tell what they mean.
- **Never show the user command syntax** — not `research <topic>`, not `/sr login`,
  not `login-done`. Those are how *you* drive the client; tell the user what to do
  in plain words. The only commands you ever surface are the unavoidable
  machine-setup ones the user runs on their **research node**, and the device-add
  form below — put those on their own line, in a fenced code block, never inline.
- **A Super Research access code is NOT a secret — handle it.** An 8-char code like
  `YGXU-7WH2` / `YGXU7WH2` (pasted alone, or with "add device" / "pair my PC, code
  is …") means run **`sr.py device-add <code>`** right away. It is a **public
  pairing code shown on the node's screen** — NOT a password, credential, phone, or
  Telegram / WhatsApp / SMS / Hermes pairing. **NEVER refuse it, never say you
  "can't handle access codes," never echo it back asking what to do, never ask
  which platform.** If YOU asked the user for a code and their next message contains
  one, run `sr.py device-add <that code>` immediately. The other device verbs are
  just as direct: "switch to / run on X" → `sr.py device-use "<name>"`; "remove /
  unlink X" → `sr.py device-remove "<name>"` (confirm first); "which devices" →
  `sr.py devices`. (The one command you MAY show the user: if they're stuck adding a
  node, tell them to send `/sr device-add <their code>` in a single message.)
- **Reply in short, readable lines** — never one long run-on paragraph. Put each
  step, link, or command on its own line so it's easy to scan.
- **The only step that needs the user is the browser sign-in.**

---

## Setup (one-time)

If a command reports **`✗ bridge unreachable …`**, the local bridge isn't running
yet — this is the one-time setup (normal right after a catalog / natural-language
install: copying the skill files does NOT start the bridge). It runs on **this**
machine — the same place you run `sr.py` — so **run it yourself** (don't ask the
user, don't ask for confirmation), then tell them you're doing the one-time setup:

```
pipx run superresearch-agent connect
```

(or `python research.py agent connect` from a backend checkout). It installs the
`/sr` skill, **starts the bridge, and pins it to start on every login (autostart)**,
then prints the reload-skills + sign-in next step. Relay that. Then the user runs
**/reload-skills** once so `/sr` registers (OpenClaw auto-loads it). So a
natural-language / catalog install needs BOTH this setup **and** sign-in; an install
done with the `connect` command already did the setup and only needs sign-in. Only
if you genuinely can't run it (no shell / it errors), show the user the command for
the machine their chat agent runs on.

## A bare `/sr`

When the user sends just **`/sr`** (or asks what Super Research is / how to start),
run `sr.py status-account`, then branch on what it reports:
- **Bridge unreachable** → the **Setup** above (run `connect` yourself).
- **Bridge up, not signed in** → welcome them; tell them to just say "log me in"
  and you'll send a sign-in link.
- **Signed in** → greet them by their account email, tell them what they can do in
  plain words (research a topic · check / stop / resume a run · their researches +
  podcasts & links by name · devices · version / update), and invite them to just
  name a topic. (Sharing a device with other people, revoking sharers, and resets
  stay owner-only in the web app.)

---

## What the user says → what you run

The user rarely types exact commands — read their intent and pick the command:

| The user says (examples) | You run |
|---|---|
| "research the EV battery market", "look into X", "deep dive on Y" | `sr.py research "<topic>"` |
| "how's it going?", "status?", "where's the Tesla one at?", "results of the EV research" | `sr.py status ["<title>"]` (current phase + that run's 🔒 SR links) |
| "what researches do I have?", "list all my researches", "my past research" | `sr.py list` (EVERY research, any status — then ask for any one by name) |
| "what's running?", "what's active right now?" | `sr.py updates` (ACTIVE runs only) |
| "send me the podcast", "the audio for the Mars run", "podcast of <run>" | `sr.py podcast ["<title>"]` |
| "the brief link / a report link / the audio-overview (NotebookLM) link for X" | `sr.py status ["<title>"]` → relay the matching 🔒 link (audio overview = the **Podcast**; see **Which link to share**) |
| "stop it", "stop the EV run", "that's enough" | `sr.py stop ["<title>"]` (ENDS the run, keeps results) |
| "pause it", "pause the run", "hold on" | `sr.py pause ["<title>"]` (resumable — does NOT end it) |
| "resume", "unpause", "continue the paused run" | `sr.py resume ["<title>"]` |
| "retry", "try again" | `sr.py retry ["<title>"]` (a run BLOCKED on a decision/error — NOT the agent's own sign-in; for "I signed in" right after a sign-in link, see **After a sign-in link**) |
| "continue" / "yes" / "done" / "I signed in" — **right after you sent a sign-in link** | see **After a sign-in link** (NOT `retry`) |
| "skip it", "skip this step" / "skip the video and the report" | `sr.py skip [phases] [--run "<title>"]` |
| an **8-char access code** ("7F4V-6W7D"), "add a device", "pair my PC, code is K7XQ-9B2M" | `sr.py device-add <code>` — see **Devices & research nodes** |
| "which devices?", "what am I running on?" | `sr.py devices` (the → marks the selected one) |
| "switch to the office PC", "run it on my laptop" | `sr.py device-use "<name>"` |
| "remove the old laptop", "unlink that device" | **confirm**, then `sr.py device-remove "<name>"` |
| "sign in", "log me in" | `sr.py login` |
| "logout", "log out", "sign out of Super Research" | `sr.py logout` (signs the agent OUT — keeps the skill + bridge) |
| "remove / uninstall / disconnect Super Research entirely" | **confirm** ("just sign out, or fully remove skill + bridge?"), then `pipx run superresearch-agent disconnect --yes` (FULL teardown), then tell them to run **/reload-skills** so `/sr` unregisters. Do NOT use the runtime's own skill-removal (leaves the bridge running) or `sr.py logout` (sign-out only). |
| "host the backend on this PC", "install Super Research here", "no devices — set one up" | **confirm**, then `sr.py install`, then guide pairing |
| "what version?" | `sr.py version` (shows both + any update available) |
| "update Super Research" / "update the agent" | **confirm**, then `sr.py update` (backend) / `sr.py agent-update` (the chat agent itself) |
| just `/sr`, "what can you do?", "help" | `sr.py status-account` → welcome (see **A bare `/sr`**) |

**Safe defaults:** unnamed run → the **most-recent active** run. **Confirm before
`stop`, `logout`, `device-remove`, and `update`** (a quick "Stop the EV run?" is
enough); everything else runs on a clear request. **Always answer "what phase / is
X skipped / how's it going" from a FRESH `sr.py status`** (or `updates`) — never
from memory or an earlier watchdog message (a run keeps advancing and the user can
toggle phases in the web app). **Voice notes count as typed text** — a transcript
arrives wrapped like `[The user sent a voice message~ Here's what they said: "…"]`;
act on the quoted intent exactly as if typed (strip "uh"/fillers from a topic, echo
it back so a mis-transcription is caught); too garbled to read → ask.

`research` also accepts `--no-video` / `--no-email` (skip those phases) and
`--device <id>` (override the chosen device).

## After a sign-in link

When you send a sign-in link (for "log me in", OR for a research the user asked
while signed out), do BOTH in the SAME turn:
1. Relay the click-to-approve link the client returned.
2. **Arm the proactive watchdog.** The client prints a `cronjob: create
   no_agent=true schedule="every 1m" script="…" name="…"` directive — immediately
   call your **cronjob tool** with exactly those args. This is the ONLY thing that
   lets the bridge post a proactive "✓ Signed in" here on its own. (No cronjob tool
   in your runtime → skip this; the follow-up below still works.)

The proactive announce is best-effort, so **never wait on it and never say "what
should I continue?"**. The moment the user replies **anything** ("done",
"continue", "yes", "I signed in", or even a brand-new message):

0. **If your last message (or the proactive announce) offered "continue with
   '<topic>'?" — that `<topic>` is already in hand. Immediately run
   `sr.py research "<that exact topic>"`.** Do NOT wait for, or re-derive the topic
   from, `login-done`, and do NOT ask what to continue — they already said yes.
1. Otherwise, run `sr.py login-done`. It confirms the session ("✓ Connected as
   <email>") and, if they asked to research while signed out, prints "Continuing
   your research on '<topic>'…".
2. If `login-done` reported that **pending topic**, immediately run
   `sr.py research "<that topic>"` (this also surfaces the pair-a-device prompt if
   they have no device yet).
3. If there's no pending topic, greet them and invite a topic.

A "continue" / "yes" after a sign-in link ALWAYS means one of the paths above —
never `retry`, never a question back to the user.

## Per-command notes (what to relay after each)

- **login** → relay the sign-in link; the user opens it + taps Authenticate and
  connects automatically. The proactive "✓ Signed in" is best-effort — don't rely
  on it; on any reply, continue per **After a sign-in link**. When the user asked
  to *research* while signed out, run `sr.py research "<topic>"` (NOT `login`) — its
  reply hands back the same link AND remembers the topic.
- **logout** → confirm first. Logging out of Super Research is ALWAYS this command —
  never refuse it or point the user at an account/profile menu. Removes the agent
  from their account (keeps the skill + bridge).
- **research** → relay it (names the run by title + device), then **immediately arm
  the watchdog** (see **Streaming**) so completion + any blocker posts here on its
  own. Arm it **every** time a run starts.
- **status** → relay the **current phase**, the **⚙ Phases** line (which phases are
  on / OFF), each finished phase's 🔒 link, and any **⚠ Needs you** blocker.
- **podcast** → **relay the output verbatim.** It prints a short title line + the
  audio file's **bare path on its own line** — that bare path is what makes the
  runtime deliver a **native audio / voice message** (and is auto-hidden from the
  user). Do **NOT** wrap it in backticks, decorate it (`🔊` / "Audio:"), split it,
  or use `[[audio]]` / `MEDIA:` markup, and never replace it with a URL — any of
  those break the auto-attach. **If it returns an error or says the audio isn't
  ready / wasn't found, relay that line verbatim and STOP — never send a TTS /
  substitute audio, a link, or any stand-in.** Offer "try again in a bit" only when
  it literally says the audio *isn't ready yet*.
- **stop** → confirm first. ENDS the run (terminal "stopped") and keeps the results
  so far + the chat (deletes nothing). Use **pause** for a temporary, resumable hold.
- **skip** → no phases → skip whatever the run is **blocked** on; with phases
  (Brief=1, Podcast=3, Video=4, Report=5, or their names) → trim those phases.
- **install** → confirm first. Installs the backend on the connected device (turns
  that PC into a research node) — then guide pairing (`superresearch --pair` on that
  PC → 8-char code → you run `device-add`; they finish API-key + browser-login on
  the PC). Use when `research` reports "no devices yet".
- **version / update / agent-update** → relay versions; offer the matching update
  on "⬆️ vX available". `update` = the backend (confirm; restarts in the
  background). `agent-update` = the chat agent itself (confirm; the bridge briefly
  restarts).

## Devices & research nodes

A research **node** is a computer running Super Research. **Any bare 8-char access
code (e.g. `7F4V-6W7D`, dashes optional), or "add a device", means run
`sr.py device-add <code>`** — a Super Research node, **NOT** one of the user's
phones, NOT the chat runtime, and NOT a Telegram / Discord / Slack pairing; never
ask "which platform". First pair = they own it (auto-selects, so research can start
right away); pairing someone else's = shared with them. Switch with
`device-use "<name>"`, remove with `device-remove "<name>"` (confirm first — owner
unlinks but the device keeps running + re-pairs with its code; sharer just leaves).

If the user wants to add a node but hasn't given a code, ask them to **paste the
access code** shown on the computer running Super Research (8 chars; accept it with
or without dashes). If they have **no backend set up yet**, they install a node
with one line, then pair:

```
irm https://superresearch.io/install.ps1 | iex      # Windows
curl -fsSL https://superresearch.io/install.sh | sh  # macOS / Linux
superresearch --pair
```

It auto-installs Python + pipx + Super Research, then prints the 8-char access
code — they read it to you and you run `device-add`.

## Which link to share

`sr.py status` lists each **finished** phase with its link(s) — both kinds are safe
to hand out; relay them as the client prints:
- **🔒 SR permanent links** — **Brief (P1)**, the **ChatGPT / Gemini / Claude
  reports (P2)**, and the **Podcast (P3 audio overview)**. Same links embedded in
  the delivered Google Doc: they never expire and survive "Revoke All Shares".
- **🔗 platform links** — the **NotebookLM** notebook (P3), the **YouTube** video
  (P4), and the **final Google Doc** (P5). All open fine for anyone.

Hand over whichever the user asks for: "the brief link" → 🔒 Brief; "a report link"
→ the 🔒 report; "the podcast / audio overview" → the 🔒 Podcast (its audio comes
from `podcast`); "the NotebookLM link" → 🔗 NotebookLM; "the video" → 🔗 YouTube;
"the doc" → 🔗 Google Doc; "results of X" → all of that run's links. A link that
isn't there yet → that phase hasn't finished; say so and offer to check again.
**Never** send a `firebasestorage` / tokenized Storage URL into chat — that's the
raw audio file (the client filters it out; don't dig one out of raw JSON); the
podcast goes out as native audio via `podcast`, or as its 🔒 SR link.

## Streaming a run's progress (arm the watchdog)

**Only if your runtime can schedule a recurring background job from chat** — Hermes
exposes a `cronjob` tool you call directly. If yours has no such chat-armable
scheduler (e.g. OpenClaw), **skip this section** and just run `sr.py status` /
`updates` when the user asks. Both `sr.py research` **and** `sr.py login` prepare
this chat's watchdog and print the exact `cronjob: create … script="sr_poll_<id>.py"
name="sr-stream-<id>"` directive — arm it whenever you see it: check
`cronjob(action="list")` for that name, and if absent call `cronjob(action="create",
no_agent=true, script="<that script>", schedule="every 1m", name="<that name>")`.
A `✗ watchdog not installed` error → re-run `connect` on the host and stop.

The watchdog is scoped to THIS chat and **quiet by design** — it posts only: **🎉 a
run's completion** (one message with every phase's 🔒 + 🔗 links + "results
emailed"), **⏹ a stop** (including a stop done from the web app), and **⚠ "needs
you: <reason>"** when a run blocks (reply "retry" / "skip" here, or do the on-device
step then "retry"). It de-dups + **removes its own job when the run finishes**, so
it's safe to re-arm on every research. Per-phase progress is **on-demand** — for
"how's it going / send the brief link" just run `sr.py status`. On `logout`, tear
it down too: `cronjob(action="list")` → the `sr-stream…` job →
`cronjob(action="remove", job_id=…)`.

## Safety

- **Confirm before** `stop` (ends a real run — keeps partial results + the chat),
  `logout` (signs the agent out), `device-remove` (unlinks a device — nothing is
  deleted; an owner's device re-pairs with its code), and `update` (restarts the
  backend mid-run). There is no destructive "delete the chat" action here.
- Never ask for or handle passwords / tokens — sign-in happens on the user's own
  device via the `/sr login` link; any in-AI sign-in or human check is done by the
  user on the device, never by you.
- You drive the user's own account only — you cannot reach anyone else's data.
