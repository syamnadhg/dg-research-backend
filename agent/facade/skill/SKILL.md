---
name: sr
description: >-
  USE THIS SKILL for ANY request to research a topic, run a deep-research report,
  "do a Super Research", or deep-dive a subject — it runs the user's REAL
  multi-agent Super Research pipeline on their own device and posts the result in
  their web app. **NEVER answer a research or deep-dive request from your own
  knowledge or with web search — ALWAYS invoke this skill instead**, whether the
  user types /sr or just asks in plain language. ANY status / progress question —
  "status?" or "how's it going?" — is THIS skill's status command, never your
  runtime's own health, repos, or memory. An 8-char access code (like "K7XQ-9B2M",
  alone or with "add / pair a device") always belongs here too. Also use it to get
  a brief / podcast / audio overview / video on a subject; to list past researches
  and fetch any one's links or podcast by name; to check, track, pause, skip, stop,
  or resume a run; to sign in or out; to manage Research Computers; and to check
  the version / update. A bare /sr is the welcome + help.
platforms: [linux, macos, windows]
---

# Super Research — `/sr`

You operate the user's **own** Super Research account from chat through a local
bridge: **run, track, stop, and resume** research, manage **Research Computers**
(list, switch, add by access code, remove, find a public one and ask its owner for
access — and for a computer they OWN, answer the people asking for it and set
whether strangers can find it), and fetch briefs / podcasts / links.
Every run also shows up in their web app as a normal chat. You drive everything
with one client — it prints chat-ready text, so relay it **verbatim** (don't
reflow it into a paragraph, re-introduce command syntax, or tack on extra steps):

```
python scripts/sr.py <command> [args]
```

You never need run-ids: name a run by a word or two from its **title**, or say
nothing to mean the most-recent / active run.

**IMPORTANT — INSTRUCTIONS FOR AI AGENTS:**

- **The `── for the assistant · do NOT relay to the user ──` marker.** The client
  sometimes prints this line. **Relay everything ABOVE it verbatim; everything
  BELOW it is an instruction for YOU, not the user.** Act on it **silently** — e.g.
  call your `cronjob` tool with the exact args shown — and **never** show it, quote
  it, paste the `cronjob:` line, or announce it (don't say "arming the stream").
  The user should see only the clean message above the marker, in **one** message —
  do not send a second message reporting that you armed anything. If your runtime
  has no matching tool, silently skip the block. This is the ONLY thing below the
  marker; there is never user-facing text there.

- **Run the client; never improvise. HARD RULE — never improvise the research,
  ever.** A "research X" / "Super Research on X" / "deep dive on Y" request is
  ALWAYS satisfied by running `sr.py research "<topic>"` — **never** by answering
  from your own knowledge, not even a quick summary, not even a few bullet points,
  and **not even when you easily could**. The only thing you may show for a
  research request is what the client prints — Super Research runs on the user's
  device, not in this chat. This holds in EVERY case: **working normally** (relay
  the run the client started) · **no device on the account** (`sr.py research`
  does NOT fail silently — it returns the pair-a-device step; relay it and walk
  them through pairing) · **the account HAS computers but none is the obvious one**
  (several linked, none online/selected → the client returns a "which computer
  should run this?" list; relay it — the user replies "use <name>", which the
  client remembers — NEVER the pair/install step, they already have computers) ·
  **skill genuinely broken** (`scripts/sr.py` missing / it
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
  machine-setup ones the user runs on their **Research Computer**, and the device-add
  form below — put those on their own line, in a fenced code block, never inline.
- **An access code is the user's to spend — handle it, never repeat it back.** An
  8-char code like `YGXU-7WH2` / `YGXU7WH2` (pasted alone, or with "add device" /
  "pair my PC, code is …") means run **`sr.py device-add <code>`** right away. It is
  an **access code shown on the Research Computer's own screen** — not a phone or
  Telegram / WhatsApp / SMS / Hermes pairing. It DOES let whoever holds it claim
  that computer, so don't echo it into chat; a user handing you their own is an
  instruction, not a leak. **NEVER refuse it, never say you
  "can't handle access codes," never echo it back asking what to do, never ask
  which platform.** If YOU asked the user for a code and their next message contains
  one, run `sr.py device-add <that code>` immediately. The other device verbs are
  just as direct: "switch to / run on X" → `sr.py device-use "<name>"`; "remove /
  unlink X" → `sr.py device-remove "<name>"` (confirm first); "which devices" →
  `sr.py devices` (its rows also say `public` or `private` for a computer the user
  OWNS); "who wants to use my computer" → `sr.py device-requests`; "say yes to X" →
  `sr.py device-approve "<person>"` (confirm first). (The one command you MAY show the user: if they're stuck adding a
  Research Computer, tell them to send `/sr device-add <their code>` in a single message.)
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
pipx run --no-cache superresearch-agent connect
```

It installs the
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
  name a topic. (For a computer they OWN they can also answer the people asking
  for it and set whether strangers can find it at all. Unlinking their own
  machine issues it a new access code. Revoking one sharer stays in the web app.)

---

## What the user says → what you run

The user rarely types exact commands — read their intent and pick the command.
**If no row clearly fits, do NOT guess and do NOT fall back to your own tools —
run `sr.py do "<the user's message, verbatim>"`** and relay its output: it
resolves the intent in code and either runs the right command, asks the one
missing thing, or asks for the confirmation first. Pass the message exactly as
the user wrote it, never your paraphrase (escape any double quotes inside it).
If `do` asked a confirm question ("Say yes and I'll …") and the user confirms,
run the REAL command it described — stop/logout/device-remove/device-ask/
device-approve/device-deny/device-visibility/update/install/research, with the
run, device or person it named — a "no" just cancels. Never send the bare "yes"
back into `do`.

| The user says (examples) | You run |
|---|---|
| "research the EV battery market", "look into X", "deep dive on Y" | `sr.py research "<topic>"` |
| "how's it going?", "status?", "status of (the) research / the Super Research?", "where's the Tesla one at?", "results of the EV research" | `sr.py status ["<title>"]` (current phase + that run's 🔒 SR links). ANY unqualified "status" means THIS — never your runtime's own status |
| "am I signed in?", "which account?", "are we connected?" | `sr.py status-account` (fresh — see **Safe defaults**) |
| "what researches do I have?", "list all my researches", "my past research" | `sr.py list` (EVERY research, any status — then ask for any one by name) |
| "what's running?", "what's active right now?" | `sr.py updates` (ACTIVE runs only) |
| "send me the podcast", "the audio for the Mars run", "podcast of <run>" | `sr.py podcast ["<title>"]` |
| "the brief link / a report link / the audio-overview (NotebookLM) link for X" | `sr.py status ["<title>"]` → relay the matching 🔒 link (audio overview = the **Podcast**; see **Which link to share**) |
| "stop it", "stop the EV run", "that's enough" | `sr.py stop ["<title>"]` (ENDS the run, keeps results) |
| "pause it", "pause the run", "hold on" | `sr.py pause ["<title>"]` (resumable — does NOT end it) |
| "resume", "unpause", "continue the paused run" | `sr.py resume ["<title>"]` |
| "retry", "try again" | `sr.py retry ["<title>"]` (a run BLOCKED on a decision/error — NOT the agent's own sign-in; for "I signed in" right after a sign-in link, see **After a sign-in link**). If the reply says the run has no Retry, relay that line — do NOT try `skip` instead. |
| "continue" / "yes" / "done" / "I signed in" — **right after you sent a sign-in link** | see **After a sign-in link** (NOT `retry`) |
| "skip it", "skip this step" / "skip the video and the report" / "skip Claude (in P2)", "drop ChatGPT from the research" | `sr.py skip [phases\|agents] [--run "<title>"]` — phases (brief/podcast/video/report) AND the P2 research agents (chatgpt/gemini/claude), same as the app's per-agent toggles |
| an **8-char access code** ("7F4V-6W7D"), "add a device", "pair my PC, code is K7XQ-9B2M" | `sr.py device-add <code>` — see **Devices & Research Computers** |
| "which devices?", "what am I running on?" | `sr.py devices` (the → marks the selected one) |
| "switch to the office PC", "run it on my laptop" | `sr.py device-use "<name>"` |
| "remove the old laptop", "unlink that device" | **confirm**, then `sr.py device-remove "<name>"` |
| "sign in", "log me in" | `sr.py login` |
| "logout", "log out", "sign out of Super Research" | `sr.py logout` (signs the agent OUT — keeps the skill + bridge) |
| "remove / uninstall / disconnect Super Research entirely" | **confirm** ("just sign out, or fully remove skill + bridge?"), then `pipx run superresearch-agent disconnect --yes` (FULL teardown), then tell them to run **/reload-skills** so `/sr` unregisters. Do NOT use the runtime's own skill-removal (leaves the bridge running) or `sr.py logout` (sign-out only). |
| "host the backend on this PC", "install Super Research here", "no devices — set one up" | **confirm**, then `sr.py install`, then guide pairing |
| "what version?" | `sr.py version` (shows the SKILL version only; nudges when a newer skill version is available. The backend's version lives in the app's Settings → About — don't mention the backend here) |
| "update", "update the skill", "update yourself" (colloquial "update the agent" too) | **confirm**, then `sr.py update` (updates the Super Research **skill** — this chat's scripts + bridge). It returns a do-not-relay finish script — FOLLOW IT: wait for the bridge to restart, verify the new version with `sr.py version` (retry a few times while it restarts), then run **/reload-skills ONCE**, then post one "✓ updated to vX" line. Do NOT improvise your own recovery. This is the ONLY thing the runtime updates. |
| "update Super Research", "update the backend", "update the research computer" | the runtime does NOT update the backend — tell them to run `superresearch --update` on the Research computer **or** update it from the app (Settings → About / the update notification). `sr.py do "<message>"` returns this exact redirect. |
| "send my logs", "share the logs with support", "submit diagnostics" | `sr.py send-logs` — it SHOWS what would go and sends nothing. On "yes", run `sr.py send-logs --confirm`. See **Sending logs to support** |
| "did my logs go through?", "check on that support code" | `sr.py send-logs --status <CODE>`. ⛔ **A FOLLOW-UP, NOT A STANDALONE ASK** — it needs the support code from the earlier reply, so `sr.py do "<message>"` cannot resolve it and will answer with the catch-all. Run the flag yourself with the code you were given |
| "just the one about X", "only the first two", "not all of them" | ⛔ **ANSWERS TO THE PLAN THIS COMMAND JUST PRINTED**, not standalone asks — `sr.py do` cannot resolve them, because the numbers exist only on the screen in front of the user. the plan numbers every run — pass those numbers back with `--runs`, comma-separated: `sr.py send-logs --runs 1,3` (and again on `--confirm`). `--runs 0` is the agent's own log, `--runs all` is every run listed. A name works too. Do **not** guess a number the plan did not print |
| "send the agent's log too", "include the bridge log", "the log from this chat" | ⛔ **SAID INSIDE THE SEND-LOGS FLOW** — on its own, "include the bridge log" names no request to add it to, so `sr.py do` answers with the catch-all. add `--agent-log` to the **bare** command **and to `--confirm`** — or say `--runs 0`, which is the same thing and is the number the plan prints for it. It uploads nothing on either; it makes the plan name it, and makes the client hand you `sr.py send-logs --status <CODE> --agent-log` for once the bundle lands. **Not** owner-gated. See **Sending logs to support** |
| "are there any public computers?", "show me computers I could ask to use" | `sr.py devices-public` (only machines whose owners offer them; the id on each row is what the next command takes — public names collide, an unnamed one reads as "Research computer" for everybody). A row marked "can't take anyone else" is full: asking would be refused |
| "I don't have a computer of my own", "I have no computer", "I haven't got a machine" | `sr.py devices` — **not** `devices-public`. It answers from the account's own list, and when that list is empty it IS the full answer: no computer here, add your own with an access code, or ask to use one of the public ones, which it lists. Sending these to `devices-public` told anybody who DID have a computer to go and ask a stranger |
| "make my computer public", "let people find my mac", "offer my machine to other people" | **confirm** — relay the client's question verbatim (strangers would see the name the computer reports, which on an unrenamed machine is often its OWNER'S own name; the user still approves each person) — then `sr.py device-visibility public` (add `"<name>"` only if they named a computer; with one machine the user OWNS the client picks it, with several it asks which — a shared machine is never picked and never offered, because its visibility is not theirs to set) |
| "make my computer private", "hide my mac", "stop offering my machine", "take it off the public list" | `sr.py device-visibility private` — **no confirmation**: it only takes a computer OFF a list |
| "is my computer public?", "which of my computers are findable?" | `sr.py devices` — the row for a computer the user OWNS says `public` or `private` (the same two words the command uses, and the web app's toggle). Do NOT change anything to answer a question |
| "who wants to use my machine?", "any requests for my mac?", "what am I waiting on?" | `sr.py device-requests` — it prints BOTH halves: people waiting on the user's OWN computers first, then what the user is waiting on from other people. Never add the two together |
| "approve that request", "say yes to Sam", "let them use my computer" | **confirm** — relay the client's question verbatim (anyone the user says yes to can run research on that computer, the same as somebody given an access code) — then `sr.py device-approve "<person>"`, or with no name when only one person is waiting. Report what the reply says: they CAN USE it, never "you just added them" — an approval of somebody who already got in changes nothing on the machine |
| "deny that request", "say no to Sam", "turn them down" | **confirm** — relay the client's question verbatim (cannot ask again for a week; the app tries to tell them, which depends on their own notification settings — the access code is still a way back) — then `sr.py device-deny "<person>"` |
| "ask for the Studio PC", "request access to that Mac", "ask its owner if I can use it" | **confirm** — relay the client's question verbatim (the research would run on THEIR computer using THEIR AI accounts, that computer can read this account's research, and they see the user's name, or email if no name is set; a "no" blocks asking again for a week) — then `sr.py device-ask "<name or id>"`. Prefer the **id** from the list: public names collide |
| "did they answer?", "my pending requests" | `sr.py device-requests` — of the ones the USER asked for, ONLY unanswered ones appear. A request that has been answered leaves that half **either way**; never read a missing row as a refusal. A **yes** shows up as the computer appearing in `sr.py devices`; for a **no**, ask for that computer again and the reply says so. The owner half above it drops a row for different reasons — a machine handed on or deleted takes its queue with it |
| "cancel my request", "withdraw that request" | nothing withdraws a request — relay the client's line. It stays with the owner until they answer, or lapses after a week |
| just `/sr` | `sr.py status-account` → welcome (see **A bare `/sr`**) |
| "what can you do?", "help", "what is Super Research", "how do I start", "options", "commands" | `sr.py do "<message>"` relays the capability line — the same list the catch-all prints, without the sentence in front that says the request was not understood. ⛔ Not `status-account`: on an account that already has a computer that prints `✓ Signed in as <email>` and nothing else |
| "the brief link", "a report link", "the NotebookLM link", "the doc", "the video" | `sr.py status ["<title>"]` — every link lives in the status output; there is no separate link command. Said on their own these name the most-recent run |
| "my past research", "my researches", "my runs" | `sr.py list` |
| "skip the podcast on \"<title>\"", "skip the video on the <title> run" | `sr.py skip <phase> --run "<title>"` — a phase of a run that is **not** the newest. Without `--run` every skip lands on the most-recent active run — or asks which run, when the user has one chat can't manage |
| "skip phase 3", "skip phases 4 and 5" | `sr.py skip 3` / `sr.py skip 4 5` — the numbers are 1 (brief), 3 (podcast/audio), 4 (video/youtube), 5 (report/email). Any other number is refused by name |
| "skip all but the podcast", "skip everything except the brief" | the **complement** — `sr.py skip brief video report` keeps the podcast. Never pass the phase they said to KEEP |
| "cancel the run" | `sr.py stop` — same as "stop"; the word `cancel` withdraws nothing else |
| "research <topic> without video", "…with no email" | `sr.py research "<topic>" --no-video` / `--no-email` |
| "send the computer's own logs" | `sr.py send-logs --machine` |

**Safe defaults:** unnamed run → the **most-recent active** run (a run verb asks
which one instead while the user has a run chat can't manage). **Confirm before
`stop`, `logout`, `device-remove`, `device-ask`, `device-approve`, `device-deny`,
`device-visibility public`, `update`, and `install`** (a quick "Stop the EV run?" is enough);
everything else runs on a clear request. The four device ones destroy nothing and
are on the list anyway, because each tells somebody something about somebody else:
`device-ask` hands the owner the user's name; `device-approve` lets a stranger run
research on the user's computer; `device-deny` stops that person asking again for
a week; and `device-visibility public` publishes the computer's name to everyone
signed in. **`device-visibility private` needs no confirmation** — it only takes a
computer off a list. **Always answer "what phase / is
X skipped / how's it going" from a FRESH `sr.py status`** (or `updates`) — never
from memory or an earlier watchdog message (a run keeps advancing and the user can
toggle phases in the web app). **Sign-in / connection state the same: ONLY from a
fresh `sr.py status-account`, never from chat history** — a bridge can sign out on
its own, and a stale "connected" answer sends the user's next research into a
surprise login wall. **Voice notes count as typed text** — a transcript
arrives wrapped like `[The user sent a voice message~ Here's what they said: "…"]`;
act on the quoted intent exactly as if typed (strip "uh"/fillers from a topic, echo
it back so a mis-transcription is caught); too garbled to read → ask.

`research` also accepts `--no-video` / `--no-email` (skip those phases) and
`--device <id>` (override the chosen device).

## After a sign-in link

When you send a sign-in link (for "log me in", OR for a research the user asked
while signed out), send the user **one** message: the click-to-approve link the
client returned. The client arms this chat's live-updates watchdog **itself** so the
bridge can post a proactive "✓ Signed in" here on its own — there is normally
**nothing for you to do**. Only if the client prints a directive **under the
`── for the assistant · do NOT relay ──` marker** (a fallback path) do you call your
**cronjob tool** with exactly those args **silently**, in the same turn. **Do NOT
send a second message about arming, and do NOT re-paste the sign-in link** (that
duplicate is the bug this avoids).

The proactive announce is best-effort, so **never wait on it and never say "what
should I continue?"**. The moment the user replies **anything** ("done",
"continue", "yes", "I signed in", or even a brand-new message):

0. **If your last message (or the proactive announce) offered "continue with
   '<topic>'?" — that `<topic>` is already in hand. Immediately run
   `sr.py research "<that exact topic>"`.** Do NOT wait for, or re-derive the topic
   from, `login-done`, and do NOT ask what to continue — they already said yes.
1. Otherwise, run `sr.py login-done`. It confirms the sign-in and **relays whatever the
   bridge already did about their research** — it is the one command that can, because it
   consumes the same one-shot note the proactive announce would have carried. Four shapes:
   - "✓ Signed in … 🚀 Started '<topic>' on <computer>" — already running. Say so; start
     nothing.
   - "✓ Signed in … '<topic>' has nowhere to run yet" — walk the pair-a-computer steps it
     prints.
   - "✓ Signed in … which should run '<topic>'?" — **relay that question with the
     computer names** and wait for their pick; then `sr.py device-use "<name>"`.
   - "✓ Connected as <email>. Continuing your research on '<topic>'…" — the cue to act:
     go straight to step 2.
2. If `login-done` named a **pending topic** with that last wording, immediately run
   `sr.py research "<that topic>"` (this also surfaces the pair-a-device prompt if
   they have no device yet). Do NOT run `research` for the first three shapes — the
   bridge has already decided, and starting again would duplicate or override it.
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
- **research** → relay the clean "🚀 Started …" message (names the run by title +
  device). The client arms the watchdog **itself** so completion + any blocker posts
  here on its own — normally nothing for you to do. Only act on a directive if one
  appears under the do-not-relay marker (fallback — see **Streaming**); never mention
  arming or paste the `cronjob:` line.
- **status** → relay the **current phase**, the **⚙ Phases** line (which phases are
  on / OFF), each finished phase's 🔒 link, and any **⚠ Needs you** blocker.
- **podcast** → **relay the output verbatim.** It prints a short title line + a
  **`MEDIA:<path>` line** — that exact line is what makes the runtime deliver the
  file as **native playable audio** (the tag is auto-hidden from the user; they
  see the title + an inline player). Keep the `MEDIA:` line **exactly as printed,
  on its own line** — do NOT wrap it in backticks or a code block, decorate it
  (`🔊` / "Audio:" / "📎 File:"), strip the `MEDIA:` prefix down to a bare path,
  add `[[audio_as_voice]]`, or replace it with a URL — any of those turn the
  playable audio into a plain file attachment or lose it entirely. **If it
  returns an error or says the audio isn't ready / wasn't found, relay that line
  verbatim and STOP — never send a TTS / substitute audio, a link, or any
  stand-in.** Offer "try again in a bit" only when it literally says the audio
  *isn't ready yet*.
- **stop** → confirm first. ENDS the run (terminal "stopped") and keeps the results
  so far + the chat (deletes nothing). Use **pause** for a temporary, resumable hold.
- **"I can’t tell which run you mean"** → a stop / pause / resume / retry / skip
  with no run named, while the user has a run chat can't manage. **Relay it and
  wait for them to name a run. ⛔ Never pick one of the listed runs for them** —
  the run they meant may be the one chat can't manage, and a stop can't be undone.
- **skip** → no args → skip whatever the run is **blocked** on. ⛔ NOT EVERY
  BLOCKER HAS A SKIP — some cards offer only Retry, and the reply will say so
  ("that card has no Skip"). **That is a real answer, not an error to work
  around: relay it as written and never substitute `stop`.** With phases
  (Brief=1, Podcast=3, Video=4, Report=5, or their names) → trim those phases;
  with research-agent names (chatgpt / gemini / claude) → turn those P2 agents
  off for the run — the same thing the app's per-agent toggles do ("skip Claude
  in P2" → `sr.py skip claude`). Mix freely: `sr.py skip claude video`.
- **install** → confirm first. Installs the backend on the connected device (turns
  that PC into a Research Computer) — then guide pairing (`superresearch --pair` on that
  PC → 8-char code → you run `device-add`; they finish API-key + browser-login on
  the PC). Use ONLY when `research` reports **"no research computer on this account
  yet"** (reason `no_devices`) — the older wording "no devices yet" is gone —
  NOT when it returns a "which computer?" list (the account already has computers;
  relay the list and let the user pick with "use <name>").
- **version / update** → `version` relays the SKILL version only (never mention a
  backend version — the app's Settings → About owns that) and nudges
  only when a newer **skill** version is available. `update` (alias `update-skill`;
  NL also handles "upgrade"/"update the skill"/colloquial "update the agent")
  updates the Super Research **skill** — this chat's scripts + bridge — confirm
  first. `update` restarts the bridge on the new version and returns a **do-not-relay
  finish script**: follow it exactly — (1) wait ~25s, (2) run `version` and retry a
  few times until it reports the NEW version, (3) run **/reload-skills once** so the
  refreshed `/sr` scripts load, (4) post one "✓ updated to vX and reloaded" line.
  Do NOT invent your own multi-step recovery — the update is self-verifying now.
  It's the ONLY thing the runtime updates. The runtime does NOT update the
  **backend** — if the user asks to update Super Research / the backend, tell them to
  run `superresearch --update` on the Research computer **or** update it from the app
  (Settings → About / the update notification; the app also notifies when a backend
  update is available).

## Devices & Research Computers

**An account with NO computer is not a dead end.** Every screen that reports it
names BOTH routes — add your own with an access code, or ask to use somebody else's —
and the full ones (`devices`, `research`, the sign-in announce) also LIST the public
computers on offer. Relay that list; never present setting up a machine as the only
route. The one-line sign-in confirmation names both routes without a list, which is
deliberate: it must not make a second call to render one.

A **Research Computer** is a computer running Super Research. **Any bare 8-char
access code (e.g. `7F4V-6W7D`, dashes optional), or "add a device", means run
`sr.py device-add <code>`** — a Research Computer, **NOT** one of the user's
phones, NOT the chat runtime, and NOT a Telegram / Discord / Slack pairing; never
ask "which platform". First pair = they own it (auto-selects, so research can start
right away); pairing a machine that already has an owner = shared with you (⛔ but one whose
owner unlinked it has NO owner, so pairing it makes you the owner). Switch with
`device-use "<name>"`, remove with `device-remove "<name>"` (confirm first — owner
unlinks but the device keeps running on a NEW access code, which the reply shows; sharer just leaves).

**Owner-only, for a computer the user owns.** `device-visibility public|private`
sets whether strangers can FIND it — discovery, not access: a findable computer is
one people can see listed and ASK for, and the owner still approves each of them
by hand. `device-requests` shows who is asking; `device-approve` / `device-deny`
answer them. ⛔ `devices-public` is the OPPOSITE direction — other people's
machines, the ones the user could ask to use. One letter apart, and picking the
wrong one either shows a list nobody wanted or publishes a computer nobody meant
to publish, so read the intent before choosing between them.

If the user wants to add a Research Computer but hasn't given a code, ask them to **paste the
access code** shown on the computer running Super Research (8 chars; accept it with
or without dashes). If they have **no backend set up yet**, they set up a Research Computer
with one line, then pair:

```
irm https://superresearch.io/install.ps1 | iex      # Windows
curl -fsSL https://superresearch.io/install.sh | sh  # macOS / Linux
superresearch --pair
```

It auto-installs Python + pipx + Super Research, then prints the 8-char access
code — they read it to you and you run `device-add`.

## Sending logs to support

When something has gone wrong and Super Research support needs to see it, the
Research Computer can package its logs and upload them under a **support code** —
eight characters the user quotes when they report the problem.

**It is always two steps, and never one.** `sr.py send-logs` prints exactly what
would leave that computer — which runs, how big, and who can read them — and
sends nothing. Only `sr.py send-logs --confirm` actually sends. **Relay the plan
verbatim and wait for a real "yes".** The computer refuses a request that does
not carry recorded consent, and that consent is the user having read those
lines. Confirming on their behalf, or running `--confirm` first because it looks
like a shortcut, makes a claim about a conversation that did not happen.

- **Which runs go** is the user's to choose, and the plan numbers them so they
  can. Everything listed goes unless `--runs` says otherwise; `--runs` takes the
  printed numbers or the run names, `0` is the agent's own log and `all` is every
  run listed. Pass the same `--runs` on `--confirm` — the two calls are separate
  processes and the second remembers nothing. ⛔ A run the plan did not list
  cannot be asked for: the list is what that computer published, and it says so
  itself when it is holding more.
- **What goes** is the logs of the runs **this user** fired on that computer,
  and nothing else. The computer decides that itself — a request cannot widen
  it. So on a shared Research Computer, sending logs never hands over anybody
  else's research.
- **The computer's own logs** — its pairing and sign-in records, its raw
  activity trail — are a separate thing and are **the owner's**. They cover
  every run that machine has ever done for everyone who uses it. Only offer
  them when the user owns the computer, and only when the problem is with
  connecting it at all rather than with a particular run. `--machine` asks for
  them; a non-owner is told no.
- **The agent's own log on THIS host** is a third thing and a third computer —
  the program running this chat, not their Research Computer. `--agent-log`
  asks for it on the bare command, so the plan names it, and `--runs 0` is the
  same request by the number the plan prints. Unlike `--machine`
  there is **no ownership gate**, so no refusal will stop you: offer it only
  when the problem is this chat reaching their computer at all. It covers the
  rotated copies as well as the newest file, not just this conversation, so it
  can reach back further than the problem being reported. ⛔ And say what it
  holds before they agree: it covers **everyone who has signed in on that host**,
  not only them, and it carries a masked form of their email address, their
  account id and the ids of the computers and runs this agent has touched. The
  client's plan prints all of that — relay it, do not summarise it away.
  ⭐ **It CAN go on its own, and that is often the right offer.**
  `--agent-log --none` — or `--runs 0` with nothing else — sends this file and
  nothing else, with **a support code of its own**, and it needs
  **no Research Computer at all**. Offer it to somebody who has no computer paired yet, or cannot reach the
  one they have, because those are exactly the people who cannot build a bundle
  for it to ride. It is still two steps: the bare command prints the plan, and
  nothing leaves until you pass `--confirm`.
  ⛔ Riding a bundle is the OTHER shape and still works the old way. When runs
  ARE going, **it does not ride the send** — so **pass `--agent-log` on
  `--confirm` too**: nothing is uploaded on that call either, and it is what
  makes the client tell the user a step is still outstanding and hand you the
  exact follow-up command. Leave it off and you get neither, and the second step
  survives only in your memory. Run that follow-up when the user asks you to
  check, never on a timer. Refused before then is by design, not a fault; a
  failure there leaves the bundle and the support code untouched; "nothing to
  add" means the log was empty.
- **No runs listed** is normal on a computer that has just been set up, and it
  is exactly the connection-problem case: offer the computer's own logs instead
  if the user owns it.
- **"Hasn't told me which runs it's holding"** is not the same as "isn't holding
  any". The first means we cannot see the list; do not turn it into a statement
  about the user's logs being gone.
- **After sending**, hand back the support code and stop. Packaging takes a
  moment. Check with `sr.py send-logs --status <CODE>` **when the user asks** —
  never on a timer.
- **A cooldown is not always ten minutes.** That is the window for the same
  person asking twice; somebody refused because another user of that computer
  asked first waits about a minute. The machine tells us only that it refused,
  never how long is left — so say "shortly", never a number, and never retry
  on a loop.

## Which link to share

`sr.py status` lists each **finished** phase with its link(s) — both kinds are safe
to hand out; relay them **as the client prints** (present them however reads cleanest
for this chat — one link per line; don't invent your own URLs):
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

## Streaming a run's progress (the watchdog)

Both `sr.py research` **and** `sr.py login` **arm this chat's live-updates watchdog
themselves** — the client writes the recurring job straight into the runtime's cron
store, so it does **not** depend on you calling any tool. **Normally there is nothing
for you to do here — just relay the clean message.** Only as a FALLBACK (a legacy
runtime the client can't write to) does it instead print a `cronjob: create …
script="sr_poll_<id>.py" name="sr-stream-<id>"` directive **under the
`── for the assistant · do NOT relay ──` marker** — if you see that, act on it
**silently** and **never show it to the user**: check `cronjob(action="list")` for
that name, and if absent call `cronjob(action="create", no_agent=true,
script="<that script>", schedule="every 1m", name="<that name>")`. **Create it
whenever that exact name is absent — do NOT skip because no run looks active yet.**
Say nothing about arming — the user only sees the clean message above the marker. A
`✗ watchdog not installed` error → re-run `connect` on the host and stop.

The watchdog is scoped to THIS chat and **quiet by design** — it posts the sign-in announce plus: **🎉 a
run's completion** (one message with every phase's 🔒 + 🔗 links + "results
emailed"), **⏹ a stop** (including a stop done from the web app), and **⚠ "needs
you: <reason>"** when a run blocks. **The ⚠ notice now names the verbs that
actually work for that particular card — relay them as written and offer
nothing else.** It de-dups, and once armed for a signed-in account it **persists** (⛔ a login listener that is never approved removes its own row) (ticking silently
between runs, removed only by `agent disconnect`) — so re-arming on every research is
a harmless no-op if it's already running. Per-phase progress is **on-demand** — for
"how's it going / send the brief link" just run `sr.py status`. On `logout`, tear
it down too: `cronjob(action="list")` → the `sr-stream…` job →
`cronjob(action="remove", job_id=…)`.

## Safety

- **Confirm before** `stop` (ends a real run — keeps partial results + the chat),
  `logout` (signs the account out), `device-remove` (unlinks a device — an
  owner's keeps running but on a NEW code), `device-ask`, `device-approve`,
  `device-deny`, `device-visibility public`, `install` (installs the backend on
  the connected computer), and `update` (briefly restarts the chat
  bridge). There is no destructive "delete the chat" action here — the four device
  ones are listed because each says something about somebody else, not because
  anything is destroyed. `device-visibility private` is not on the list: it only
  takes a computer off a list.
- **`send-logs` confirms differently and more strictly**: the bare command prints
  what would leave the user's computer and sends nothing, and `--confirm` is the
  only thing that sends. Relay the plan and wait for a real "yes" — the computer
  refuses a request that does not carry recorded consent, and that consent IS the
  user having read those lines. See **Sending logs to support**.
- Never ask for or handle passwords / tokens — sign-in happens on the user's own
  device via the `/sr login` link; any in-AI sign-in or human check is done by the
  user on the device, never by you.
- You drive the user's own account only. Three things reach past it, and all three
  are consent moments where the client refuses nothing — so YOU are the consent
  step every time. **Asking** for a public computer tells that owner the user's
  name — or their email, if no name is set — and a refusal blocks asking again for a
  week. **Answering** somebody lets a stranger run research on the user's own
  computer, exactly as an access code would, and a "no" spends that person's week —
  the app tries to tell them (their own notification settings decide), and giving
  them the access code is still the way back. **Publishing**
  a computer puts the name it reports in front of everyone signed in, and a machine
  nobody has renamed usually reports its owner's own name. Never do any of the
  three on the user's behalf without a real "yes" to the client's own question.
