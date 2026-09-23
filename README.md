# Super Research — Backend Pipeline

Automates multi-agent deep research across 6 platforms. Tiered automation: Playwright/DOM (primary) → CUA (Anthropic Computer Use, current fallback). Claude Sonnet vision is wired in as tier-2 but is **off by default** — `DG_VISION_TIER=off`, so out of the box Vision is not invoked at any wire-in site. Set `shadow` and it observes CUA's actions and logs agreement; set `act` and it drives as tier-2, with CUA kept as the tier-3 safety net. *(This line used to say shadow mode was on "today", which the env table two thirds of the way down this same file already contradicted: per-hotspot promotion is waiting on shadow telemetry nobody is collecting by default.)*

> **Jira:** [DGOPS-6933](https://distributedglobal.atlassian.net/browse/DGOPS-6933)
> **Repo (this one):** github.com/dg-eng/super-research-backend
>
> No admin keys, no JSON files to copy around. `--pair` mints an 8-char
> code in the terminal; you paste it into the web app once. Per-device
> Firebase refresh tokens live in your OS keystore — Windows DPAPI,
> macOS Keychain, Linux libsecret.

## Google accounts: use personal accounts, not workspace ones

The web app side accepts any Google sign-in. **The backend is different — use a personal Gmail/Google account here, not a Google Workspace one.** Phase 0 logs the backend's Chrome session into NotebookLM, ChatGPT, Claude, and Gemini on your behalf, and Workspace-managed accounts hit the admin-approval gate on each of those services. Personal accounts skip that prompt and let the pipeline run unattended. If you've already paired with a Workspace account and Phase 0 stalls on a "this app needs admin approval" screen, the fastest fix is `python research.py --unpair` then re-pair with a personal account.

Pairing-side data scope: this backend pairs to a single web-app account at a time via `--pair`. The ResearchToken minted during pairing is bound to that uid; the backend rejects start requests whose `uid` doesn't match the token's `linkedUid`, so even if the token leaks it can't be used to drive runs against another user's research collection.

## Platform support

| Platform | Server | `--pair` | `--resurrect` / `--retire` | `--unpair` |
|----------|--------|----------|----------------------------|------------|
| Windows 10 / 11 | Full | Full | Full (Scheduled Task) | Full |
| macOS | Full | Full | Full — launchd user agent | Full |
| Linux desktop (X11/Wayland) | Full | Full | Full — systemd-user unit | Full |
| Linux headless / WSL / Docker | **Unsupported** — Chrome needs a real display + user session for CAPTCHA / 2FA / login refresh |

The supervisor (`--resurrect` / `--retire`) is cross-platform first-class on all three desktop OSes: Scheduled Task on Windows, launchd user agent on macOS (`~/Library/LaunchAgents/com.dgresearch.supervisor.plist`), systemd-user unit on Linux (`~/.config/systemd/user/dgresearch-supervisor.service`). All three share the same `--env-file` config flow (see [`.dg-supervisor.env`](#step-2-environment) below). Linux also requires `sudo loginctl enable-linger $USER` so the user-systemd manager survives logout; `--resurrect` probes and surfaces a WARN if Linger=no.

### Python version — the installed build is per-CPython-minor

**Python 3.11+ is the floor for a SOURCE checkout.** The published `superresearch`
package is different: it ships **compiled** platform wheels (Nuitka), and a
compiled extension is built against **one** CPython minor. So a release carries
one wheel per platform + CPython minor, and pipx needs an interpreter matching
one of them — "3.11+" is not sufficient on that path.

The installer handles this for you: it reads the latest release's file list,
derives which minors that platform has a wheel for, and installs (or fetches) a
matching Python. You only need to care when installing by hand — check the
filenames on PyPI and match the `cp3XX` tag. As of 0.1.13 that is Windows
`cp314`, macOS `cp313` (arm64 only), Linux `cp312` (x86_64). Different minors
across platforms are **expected**, not an inconsistency: each box builds on its
own interpreter.

A **source** checkout has no such constraint — it runs on any 3.11+.

> **What "compiled" means for the layout.** In a shipped wheel `research.py` is
> replaced by a small readable launcher shim that re-exports only `main` (so
> `superresearch = research:main` still resolves, and `--version` stays instant
> because the heavy import is lazy); the pipeline itself is
> `_sr_core.<abi>.pyd`. So `from research import <helper>` — which
> `vision.py` and `narrate.py` used to do to reach the canonical API-key
> resolvers — raises `ImportError` in **every** shipped build. Sibling modules
> now go through `models.core_attr()`, which tries `research` then `_sr_core`
> (`CORE_MODULE_NAMES`) and prefers whichever is already imported. If you add a
> module, add it to `pyproject.toml`'s `py-modules` **and** to the build's
> `TOP_MODULES` — `tests/test_compiled_wheel_covers_every_module.py` holds three
> drift guards, including "every module research.py imports must be shipped",
> which is the one that catches a module absent from *both* lists.

## Before you start (prerequisites checklist)

- **Python 3.11+** (`python --version`).
- **Real Google Chrome** installed (not just Chromium — patchright launches with `channel="chrome"`). Chrome itself is an OS-level prerequisite; the patchright Chrome wrapper, though, is **auto-fetched by `--pair`** — Stage 5 calls `_ensure_chrome_ready()`, which runs `patchright install chrome` before it opens the login tabs, so you don't have to do that step by hand. ⛔ **`--doctor` does not fetch it** — this bullet used to say it did. Doctor only *probes* the launch, and when Chrome won't boot it prints `patchright install chrome` as a **manual step** for you to run; a red row there is the probe telling you the truth, not an auto-fetch that failed.
- **Anthropic API key** with browser-automation access (`ANTHROPIC_API_KEY`; see Step 2).
- **Super Research web app account** — sign in at the deployment URL the dev shares with you (Google sign-in). You'll paste the 8-char code into **Account → Pipeline Connection** during `--pair` Stage 1.

> **Two naming notes, so the doc and the screens agree.**
> **(1) The app calls it the "access code".** Every label, error and placeholder in the web app says *access code*, and the pairing terminal now prints `Access code` above the eight characters. The wire names deliberately did **not** move — `pairCode`, `PAIR_CODE_SHOWN`, `/api/devices/pair-code`, `/api/devices/reset-pair-code` and the `--pair` verb itself are identifiers something else reads, and renaming one is a defect, not a cleanup. This README keeps saying "pair code" where it means the CLI/wire concept.
> **(2) Two nav paths that are easy to get wrong.** Entering a code is **Account → Pipeline Connection → + add device** — while a computer is already listed that section shows **no code field**, only the `+ add device` button at its foot (with no computer listed the field is already on screen and no button renders). And ⛔ **"Account → Manage devices" is not a page**: Reset and the device list live under **Settings → Manage devices**; the Account page carries the device *tiles*, each with an Unlink button.
- **Paid Pro tiers on ChatGPT, Claude, and Gemini** — required for the depth Phases 1–2 were tuned against:
  - **ChatGPT Pro** ($200/mo per seat) — Phase 1 brief uses Pro + its latest thinking model.
  - **Claude Pro** ($20/mo per seat) — Phase 2 Claude agent uses the **Opus family** + Max effort + the Research tool (Free tiers don't expose Opus or Research).
  - **Gemini Advanced** ($20/mo per seat, via Google One AI Premium) — Phase 2 Gemini agent uses the **Flash family** + Deep Research.

> **No model version is hard-coded for Phase 2** (owner directive, 2026-08-01 — `P2_MODEL_POLICY` in `models.py` is the single source of truth). The rule is **family + highest-offered**: among the rows the platform's own picker actually shows, take the highest member of the family, so a new release needs no code change and cannot be a downgrade. Claude asks for `opus` (falling back to the `sonnet` family only once the DOM has *proved* every Opus row is a sales chip — i.e. a non-Pro account); Gemini asks for `flash` and explicitly **rejects** Lite, Pro and Deep Think rows (Gemini-Pro Deep Research hangs); ChatGPT has no P2 model picker at all, only the Deep-Research toggle. The old frozen floors (`claude >= 4.8`, `gemini >= 3.5`) are gone — a floor rots in both directions, and `>= 4.8` is how P2 sat on Opus 4.8 for the whole Opus-5 rollout.
  - The pipeline will *run* end-to-end on Free tiers, but Deep Research depth, image quality, and turn limits are far lower. **A non-Pro account is flagged with a `[Continue with Free] [Retry]` alert** — via the in-phase tier tells by default (ChatGPT's P1 Pro selector, Gemini's P2 DOM read), or Phase 0's vision check when the opt-in "Verify sign-ins before each run" Setting is on — sign in with a Pro account in the same browser, then click Retry. Opting into Free for one platform suppresses the prompt for the rest of the run, so verify Pro is active in each platform's account/billing page before pairing to avoid surprises. (Stop is always reachable from the chat-box during a paused pipeline — no separate Stop button on the alert.)
- *(Optional)* Gemini API key — powers the narrator (Gemini Flash is the narration **primary** — see `GEMINI_TEXT_MODEL` in the env-var table for the pinned release — with Anthropic Haiku 4.5 as the cross-vendor fallback); narration silently disables without any key. (Phase 4 — YouTube upload — and Phase 5 — Google Doc creation + email — both run entirely in the frontend; no BE-side Resend / YouTube / Docs setup needed.)

## Quick Start

### Option A — Install as a command (recommended)

The backend installs as a `superresearch` console command via [pipx](https://pipx.pypa.io). No checkout to manage, and it runs from **any directory** — data + config live under `~/.super-research/` and `.dg-supervisor.env`.

**One command** — also at **[superresearch.io/install](https://superresearch.io/install)** (ensures Python 3.11+ & pipx — auto-installs pipx if missing — then installs `superresearch`):

```bash
# Windows (PowerShell)
irm https://superresearch.io/install.ps1 | iex

# macOS / Linux
curl -fsSL https://superresearch.io/install.sh | sh
```

Or, if you already have pipx:

```bash
# 1. Install
pipx install superresearch

# 2. Pair (one-time: mints an 8-char pair code, prompts API keys, runs browser logins)
superresearch --pair      # auto-fetches the patchright Chrome wrapper for you

# 3. Start the server (keep it running)
superresearch --serve

# One-shot CLI run (no pairing / Firebase round-trip — see § CLI Mode)
superresearch "your topic"
```

> **`superresearch <flags>` is a pure drop-in for `python research.py <flags>`** — identical flags, identical branded UI, and the same `--pair` / `--login` / `--update` / `--restart` / `--serve` / `--resurrect` / `--retire` / `--visibility` / `--unpair` / `--doctor` / `--send-logs` / `--uninstall` / `--version` / `agent` verbs. Help is invocation-aware: it shows `superresearch …` when launched from the installed command, `python research.py …` from a source checkout. So every `python research.py …` example below works verbatim as `superresearch …` on an installed build.
>
> **`--update`** updates an installed build and is **idempotent** — it checks PyPI and only reinstalls the pipx package when the installed build is actually outdated, otherwise it says "already up to date" (no pointless reinstall). This is the CLI path for updating the backend; the app's Settings → About Check → Update is the remote equivalent (a source checkout updates with `git pull` instead).
>
> ⛔ **An update is not live until you restart.** `--update` detaches the pipx upgrade and exits; the running backend keeps the OLD build in memory until it is cycled. Follow it with **`--restart`** (see [Step 5a-ter](#step-5a-ter-after-an-update---restart)) — and do not use `--version` as the confirmation, because it reports the **installed** build, so it reads as success while the old code is still serving. The honest confirmation is the device going green in the app. The same applies to an upgrade that arrived by any other route (a bare `pipx upgrade`, or the superresearch.io installer, which prints the `--restart` step itself).

### Option B — From source (developers)

```bash
# 1. Install
git clone https://github.com/dg-eng/super-research-backend.git
cd super-research-backend

# macOS / Linux: create + ACTIVATE a Python 3.11+ virtual env FIRST.
# (macOS ships python3 3.9 — too old — and Homebrew/system Pythons are
# "externally managed" (PEP 668), so a bare `pip install` is refused. The
# venv is the supported way; `uv` is fastest, plain venv works too.)
python3.11 -m venv .venv && source .venv/bin/activate   # or: uv venv --python 3.11 && source .venv/bin/activate
# Windows: a system Python 3.11+ works directly; a venv is optional.

pip install -r requirements.txt
python -m patchright install chrome    # downloads patchright's stealth Chrome wrapper

# 2. Pair (one-time: mints an 8-char pair code, prompts API keys, runs browser logins)
python research.py --pair

# 3. Start the server (keep it running)
python research.py --serve

# 3a. (Optional, recommended) Survive reboots + crashes (cross-platform).
python research.py --resurrect

# 3b. (Undo 3a) Disable On Startup — kills supervisor + serve, removes
#     the scheduled-task / launchd / systemd unit, syncs the Firestore flag.
#     Pairing stays.
python research.py --retire

# 3c. (Full disconnect) Clean teardown — deletes the device server-side
#     via /api/devices/unpair-self, wipes pairing + the OS keystore entry.
#     Tile disappears across every browser within a second.
python research.py --unpair
```

> **macOS / Linux — the venv is per-terminal.** After the one-time setup above, run `source .venv/bin/activate` in **every new terminal** before `python research.py …` (the prompt shows `(.venv)` when it's active) — then it behaves exactly like Windows. This applies only to a **source checkout**; the installed `superresearch` command (Option A, via pipx) manages its own isolated env, so end users never touch a venv. If you'd rather not activate each time, use `uv run python research.py …` or alias the venv's Python.

That's it. Three commands to a hands-off always-on backend — plus `--retire` to disable On Startup or `--unpair` to fully disconnect this PC.

> Run `python research.py --help` (or `-h`) anytime for a branded, use-case-grouped reference card. `run_commands_help` renders seven sections — Daily / Lifecycle / Agent / Advanced / Diagnostics / Local API / Internal-Debug. There is no separate `--commands` flag: it was folded into `--help`, which is now the **only** discovery surface (`argparse` runs with `add_help=False` and nothing calls `print_help`, so a verb missing a row on that screen is a verb no user can find).
>
> ⛔ **It is not a complete list, and by the rule above that matters.** This paragraph used to claim the card covered *every* CLI verb; four real ones have no row on it — **`--login`, `--update`, `--send-logs`, `--uninstall`** — and the function's own source comment names exactly those as the ones that "shipped undocumented: they have help strings and no row here." Until somebody adds the rows, this README is where they are discoverable. (The Daily row also still describes `--pair` as a "5-stage guided setup" — the flow is six stages, see [Step 3](#step-3-run-pair-flow); the screen is the stale half, not the doc.)

> **Just want to smoke-test from the terminal first?** Skip pairing entirely and run `python research.py "your topic"` — see [§ CLI Mode](#cli-mode). No code, no Firebase round-trip, output lands in `queues/`.

> **Order of ops:**
> - Steps 1 (install) and 2's API-key prep can run in parallel.
> - You're **blocked** on a web-app account before `--pair` Stage 1 finishes (paste the 8-char code into Account → Pipeline Connection).

## Drive it from chat — Super Agent (Hermes / OpenClaw)

Run Super Research from a chat runtime instead of the terminal — every run still
shows up in the web app as a normal chat. It's just another `research.py`
command (no extra install — the two deps are already in `requirements.txt`):

```bash
python research.py agent connect      # install the skill into your runtime (auto-detects hermes/openclaw)
python research.py agent serve        # start the bridge that holds your account session (keep running)
# then, in chat:  /reload-skills once (the gateway caches its skill scan),
#                 then  /sr login  →  /sr research <topic>  →  /sr status
#                 (there's one /sr command — actions follow it; bare /sr = welcome/help)
```

> On an installed build, the same front door is `superresearch agent connect` (and the other `agent` verbs). The chat-runtime agent is a **separate package** — the installed `superresearch agent <verb>` delegates to `pipx run superresearch-agent <verb>`, which installs the `/sr` skill into Hermes/OpenClaw; a source checkout runs the in-tree agent instead.

The agent runs / tracks / cancels research **and** can add (pair by access
code), switch, or remove Research Computers from chat (bridge routes
`/device/pair`, `/device/select`, `/device/remove`, `/install-backend`).

It also carries two **owner** verbs now — this paragraph used to call both of
them web-app-only:

- **Review and answer access requests.** `GET /devices/requests` lists both
  halves of the queue; `POST /device/decide` approves or denies one
  (`sr device requests` / `device approve` / `device deny`). Approving IS
  sharing — the web app's `access-request/decide` route writes the requester
  into the machine's `sharedWith[]` and syncs the custom claim.
- **Set who can find the machine.** `POST /device/visibility`
  (`sr device visibility public|private`) writes the same field `--visibility`
  and the Shared-with popup write. The agent is one of the writers
  `firestore.rules` names by role — see [§ `--visibility`](#step-5a-bis-who-can-find-this-pc---visibility).

What still has **no** chat route and stays in the web app: **revoking an
existing sharer** (chat `device remove` unlinks *you*, not somebody else) and
**resetting the access code**. Full command list:
`python research.py agent --help`. How it works + the chat slash commands:
**[`agent/README.md`](agent/README.md)**.

## Pairing model (no JSON keys to copy around)

The backend authenticates as a per-device **synthetic Firebase user**
whose long-lived refresh token lives in your OS keystore — Windows
DPAPI / macOS Keychain / Linux libsecret (with a `chmod 0600` file
fallback). No service-account JSON. No god-mode credentials shared
across devices.

The handshake at `--pair`:

1. BE mints a 256-bit `pollSecret` locally and POSTs `sha256(pollSecret)`
   to the FE Cloud Function `/api/devices/initiate-pair`. The function
   creates a synthetic Firebase Auth user and returns
   `{ deviceId, pairCode }` — an 8-char code from a confusion-resistant
   alphabet (digits 2-9 + uppercase A-Z minus I/L/O).
2. The terminal prints the code + a scannable QR. You open the web app
   → **Account → Pipeline Connection** (press **+ add device** first if
   a computer is already listed) → paste the code. The FE claim Cloud
   Function mints a customToken scoped to this device + you (with
   custom claims `ownerUid` + `deviceId`) and writes it to a subdoc
   keyed by `sha256(pollSecret)`. Sharers know the deviceId but not
   the secret hash, so the customToken is unreadable to them.
3. BE polls that subdoc (anonymous Firestore REST — `allow get: if true`
   on the keyed path), exchanges the customToken for a refresh+ID
   token pair via Firebase REST, saves the refresh token to the OS
   keystore.

> ⛔ **THE CODE IS NOT A FIELD ON THE DEVICE DOCUMENT ANY MORE.** It used to be,
> and `devices/{deviceId}` is read WHOLE by the owner, every sharer and the
> machine — Firestore cannot scope a read to fields — so the FE's device
> listener was handing every sharer the code continuously, with only a render
> condition in front of it. It now lives beside `pollSecretHash` in
> `_internal/device_secrets/entries/{deviceId}`, which is `allow read, write:
> if false` for every client. The BE learns its code exactly once, from the
> `initiate-pair` response above (`auth/v2_flow.py` returns
> `{deviceId, pairCode}`); it never reads it back out of Firestore. A person
> asks for it through the owner-gated `POST /api/devices/pair-code`.
> ⚠ The **expiry** deliberately stayed on the device doc as `pairCodeExpiresAt`:
> a TTL `fieldOverride` on collectionGroup `entries` would delete the whole
> secrets entry, `pollSecretHash` with it.

From then on, every BE Firestore write goes through that refresh token
+ google-cloud-firestore. The refresh token rotates each refresh cycle
(~1h) and the keystore rotation slot guarantees a clean swap under
parallel-process contention.

**Shared devices.** Same 8-char code drives sharing — a second account
pastes the same code into Account → Pipeline Connection and the claim
function appends their uid to `sharedWith[]`. They can submit research that
runs on your PC but can't read your other data; per-device Firestore
rules enforce the boundary via the BE's custom claim.

**Reset Pair Code** *(the app calls this **Reset** — that is the label on both
the per-device row button and the confirm dialog; "Reset access code for
&lt;machine&gt;?" is the dialog's heading, not a button. This note used to send
you hunting Settings for a button reading "Reset access code".)*
Settings → Manage devices → Reset rotates the
code, revokes the BE's refresh token, clears `sharedWith=[]`, and
emails you the new code with a 15-min TTL. The BE's recovery watcher
notices the revoke, polls the same pending subdoc, picks up the new
customToken once you enter the new code in the FE, and then replaces
itself so a fresh keystore and fresh listener subscriptions come up
together — a clean exit under a supervisor, a re-exec without one.
**No `--pair` on the PC needed.**

> ⛔ **THE WATCHER ONLY EXISTS INSIDE A RUNNING `--serve`.** This
> paragraph used to promise the device is back "within ~5s of you
> entering the new code", with no mention of that. On a machine that is
> switched off, or that runs `--serve` by hand and is not running it
> right now, nothing recovers at all: entering the code does nothing
> visible, the computer silently drops off the public device list, and
> waiting does not help because there is no timer involved — it is
> waiting for a process. Start `--serve` and recovery happens in about a
> second. Measured on an owner's machine, 2026-09-06, after several
> hours of it appearing to have crashed.

Miss the 15-min window and the device record itself expires; only then
is `--pair` the answer, and it creates a NEW computer rather than
recovering this one.

What Reset does to **in-flight runs** (multi-worker safe): the FE
route writes a `hard_reset` command to `devices/{id}/commands/`
**before** revoking refresh tokens. Every worker subscribes to that
subcollection (`_start_device_command_listener`) so all N workers
process the command independently — each touches `.stop` on its own
active run dir, flips its own active research doc to `cancelled`, and
schedules `os._exit(0)` so the daemon-loop respawns it clean. **No
zombie runs.** The route polls up to 5s for the BE to ack (delete the
command) before proceeding to revoke; if the BE is already wedged
the 30s stale-gate (`STALE_COMMAND_AGE_MS`) ensures a respawned BE
won't re-fire it.

What Reset does to **queued runs**: the FE route stamps
`expireAt: now+15min` + `cancelledReason: "device_pair_expired"` on
every user-tree research doc that points at this device (owner +
every sharer + every previously-revoked sharer, in `queued` /
`ongoing` / `running` / `paused` / `paused_pending_repair` state)
plus every `devices/{id}/queue/*` subdoc. Firestore TTL (configured
via `firestore.indexes.json` `fieldOverrides`) auto-deletes them at
the 15-min mark — sharer's research page clears the orphans
automatically via the existing real-time listener. The sharer sees
no Cancelled card to dismiss; rows just disappear.

**If you re-pair within 15 min**: the claim route's
awaiting-re-pair branch reads the snapshotted `preResetUids` field
from the device doc, clears the `expireAt` + `cancelledReason`
fields across every sharer's user-tree, and clears `expireAt` on
the queue subdocs. Queued sharer + owner runs resume seamlessly on
the post-respawn BE — sharer never sees a blip beyond the brief
"device offline" interval during the 15-min window.

**If you don't re-pair within 15 min**: device doc + all sharer
research docs + all queued runs vanish from every browser at the
15-min mark. To restore, run `python research.py --pair` on the PC.
Sharers will not regain access until you explicitly re-share with
them (post-Reset `sharedWith[]` is empty, even if you re-pair).

Partial-failure semantics: both the cross-tree expireAt set (Reset)
and the cross-tree clear (re-pair) wrap each user-tree batch in a
3-attempt retry with 250ms × attempt backoff. Persistent failures
surface as `[reset-pair-code] expireAt set FAILED after 3 attempts`
or `[claim] re-pair expireAt clear FAILED after 3 attempts` log
lines — single-RPC blips are absorbed.

What Reset does NOT touch: `~/.super-research/browser-profile*/`
directories (your Google/ChatGPT/Gemini/Claude logins survive),
`workerCount` in `research_config.json`, the supervisor (daemon-loop
keeps respawning workers on the same ports — `--retire` is the only
way to stop it), the OS keystore (the recovery watcher needs the
existing `pollSecret` from `research_config.json` to redeem the new
customToken).

## Setup Details

### Step 1: Install Dependencies

```bash
# macOS / Linux (source checkout): make a 3.11+ venv and ACTIVATE it first —
# the OS python3 (3.9 on macOS) is too old and system/Homebrew Pythons refuse
# a bare `pip install` (PEP 668). Re-run `source .venv/bin/activate` in each
# new terminal. Windows: skip this — a system Python 3.11+ works directly.
python3.11 -m venv .venv && source .venv/bin/activate   # or: uv venv --python 3.11 && source .venv/bin/activate

pip install -r requirements.txt
python -m patchright install chrome
```

Requires **Python 3.11+** and a working **real Google Chrome** install, plus `patchright>=1.61` and `playwright>=1.61` (floors bumped 2026-06-30 — both are pinned in `requirements.txt`). `research.py` launches via `patchright` (a stealth Playwright fork) with `channel="chrome"` — it uses your installed Chrome binary, NOT bundled Chromium, so anti-bot heuristics see a real browser fingerprint.

If Chrome itself isn't installed, install it first:
- **Windows:** [google.com/chrome](https://www.google.com/chrome/) → run the installer.
- **macOS:** `brew install --cask google-chrome` (or download from google.com/chrome).
- **Linux (Debian/Ubuntu):** `sudo apt-get install google-chrome-stable` (after adding Google's apt repo) or download the `.deb` from google.com/chrome.
- **Linux (Fedora/RHEL):** `sudo dnf install google-chrome-stable` (after adding the repo) or `.rpm` from google.com/chrome.

`python -m patchright install chrome` then downloads the stealth wrapper that drives that Chrome. Do this once on every machine.

`qrcode>=8.0` is already listed — the pair flow renders a scannable QR in your terminal. It is cosmetic only: if the library is missing, pair logs one INFO line and nothing else happens — the 8-char code was already printed a few lines **above**, under the `Access code` heading, where the QR would have gone. ⚠ This README said "below", and so do the source comment and the log string it was copied from; the print order is code first, `import qrcode` second. Nothing is lost either way, but look up, not down.

### Step 2: Environment

The supervisor reads env vars from `.dg-supervisor.env` (created automatically on first `--resurrect` from `scripts/dg-supervisor.env.example`). Edit that file to set Vision/CUA config; no shell-rc / `setx` needed.

**API keys** — Anthropic powers the agents (CUA + Vision) and is **required** for browser automation. Gemini powers narration + acts as the Haiku fallback for title refinement, and is **optional** (narrator silently disables without it). Four ways to set either, **all platforms**:

- **(easiest — recommended)** **`--pair` Stage 4 auto-prompt.** At the end of pairing, `--pair` checks whether each key is already resolvable from any source; for missing keys it prompts with `[paste / S=skip]`, **verifies** the pasted key against the provider's API (5s cheap probe), and on success writes BE-local persistence + `os.environ` + busts the resolver cache. Persistence is per-machine: Windows User-scope env on Windows; `.dg-supervisor.env` upsert on macOS / Linux. Skip is first-class per key.
- **(equivalent — set later, or rotate, or sync across devices)** "Account → API Config" in the web app — writes `users/{uid}/settings/prefs.apiKeys.{anthropic,gemini}` in Firestore. Distinct surface from pair-time keys: pair never auto-fills these inputs, so anything you see there is something you typed there. Works on Windows, macOS, Linux. No restart required after rotating; backend re-reads on next call (60s cache).
- **(file-based, all platforms)** Uncomment `ANTHROPIC_API_KEY=sk-ant-...` and/or `GEMINI_API_KEY=AIza...` in `.dg-supervisor.env`. Loaded by `--env-file` at supervisor startup; survives reboots via the persistence supervisor. Good for un-paired backends or operators who prefer files. (On POSIX, `--pair` writes here too.)
- **(advanced / legacy)** Set in your shell rc (Mac/Linux) or via PowerShell `[System.Environment]::SetEnvironmentVariable(..., 'User')` (Windows user-scope). The canonical env-var names are `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` (matching the Anthropic SDK + Gemini API docs). Legacy aliases `CUA_API_KEY` and `GOOGLE_API_KEY` are auto-migrated on next startup and removed; new BE versions only read the canonical names. (On Windows, `--pair` writes here too.)

**Don't set the same key in multiple places with different values** — pick one. Submitter-aware priority chain (#928 per-device + #938 sharer keys), highest first:

1. CLI `--api-key` (Anthropic only).
2. **Run-submitter's per-device key** — `users/{submitterUid}/deviceKeys/{deviceId}`, and only when the submitter ≠ the device owner. That is a sharer's own key, used ONLY for their runs, and only the `anthropic` / `gemini` fields of it (`_SHARER_OVERRIDABLE_FIELDS`).
3. **Owner's per-device key** — `users/{ownerUid}/deviceKeys/{deviceId}`. The canonical home.
4. **Owner's LEGACY `apiKeys.byDevice.{deviceId}` map** inside `settings/prefs` — still read, for an account that hasn't signed in since the move. Layer 3 outranks it because the FE writes only layer 3 now and sweeps this one on sign-in.
5. **Owner's flat FE Account-page key** — `settings/prefs.apiKeys.{anthropic,gemini}`.
6. Windows user-scope env (where `--pair` persists on Windows).
7. `os.environ` (the `.dg-supervisor.env` file loads here on POSIX, including pair-time keys).

A newer FE key wins over a stale BE-local pair key. Owner-submitted runs are unchanged from before per-device keys; a sharer's key never touches the owner's runs.

> ⛔ **This chain used to name `apiKeys.byDevice.{deviceId}` as the storage
> location for both parties.** It is neither: for the owner it is the legacy
> fallback (layer 4 above), and the sharer path never reads it at all —
> `_read_submitter_device_keys` reads one document, `deviceKeys/{deviceId}`,
> and nothing else. § [Multiple Users](#multiple-users-same-backend--sharing-via-pair-code) 350 lines down had the right
> answer the whole time; the two paragraphs disagreed.

**Other config** (Vision tier, CUA model overrides, shadow log path) also lives in `.dg-supervisor.env`. See `scripts/dg-supervisor.env.example` for the documented template + key descriptions.

> P4 thumbnail generation lives on the FE: `web/src/lib/album-art.ts` calls Gemini image-gen from inside `/api/uploadYouTube` using the FE-side env key or the user's per-prefs key. BE never owned a thumbnail role post-2026-05-10.

**Phases 4 + 5 are FE-owned.** No BE setup needed for either. The frontend handles YouTube upload via `youtube.videos.insert` (Data API + OAuth refresh token, ffmpeg encode in Cloud Run) AND Google Doc creation via the Docs API AND email via Resend — see the FE README for that side's env vars (`GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN`, `RESEND_API_KEY`, `NOTIFY_FROM_EMAIL`).

`BUG_REPORT_EMAIL` is optional — see the env-var table.

### Step 3: Run pair flow

```bash
python research.py --pair
```

The flow has **six** gated stages — each waits for the previous to confirm before advancing. (Renumber history: 4 → 5 stages with the 2026-05-18 pair-prompt addition; 5 → 6 on 2026-09-17, when the discoverability question — which had been asked inside Stage 2 as an unannounced second question — was given its own displayed step. Nothing about the flow's behaviour changed with that split: both answers are still written to Firestore in a **single** patch, because the rule they land on refuses the whole update if one key is off-list.)

> ⛔ **The telemetry stage number and the displayed step number are deliberately different since 2026-09-17.** `PAIR_STAGE_REACHED` still emits 2 / 3 / 4 at the same three code points and `PAIR_COMPLETED` still carries `stage=5`, because those numbers are identities in a time series: renumbering them would make every historical row mean something new. Displayed step → emitted stage: 2/6 → 2, 3/6 → *(none)*, 4/6 → 3, 5/6 → 4, 6/6 → `PAIR_COMPLETED` 5.

**`[1/6] Token setup` — mint + render code+QR + wait for app to claim**
Mints (or reuses) a 256-bit `pollSecret` and POSTs `sha256(pollSecret)`
to the FE Cloud Function `/api/devices/initiate-pair`. The function
creates a synthetic Firebase Auth user, allocates a unique 8-char pair
code, and returns `{ deviceId, pairCode }`. The terminal prints the
code under the heading `Access code` — the web's own word for it — in
big mono digits with a dash at position 4 (`K7XQ-9B2M`), and an ASCII
QR right below; the BE then polls
`devices/{deviceId}/pending/{sha256(pollSecret)}` (anonymous Firestore
REST) every ~2s for a customToken. Two ways to claim:
- **Type** — Super Research app → **Account → Pipeline Connection**
  (press **+ add device** first if a computer is already listed) →
  paste the 8-char code → submit. Works on any device with the app open.
- **Scan** — phone camera on the QR. ⛔ The QR encodes the **bare
  8-char code**, not a deep link — this paragraph used to promise it
  "deep-links to Account → Add Device with the code pre-filled", which
  is not what `qr.add_data(pair_code)` writes. Scanning hands you the
  code; you still open the app and paste it.

> **Don't have a web app account yet?** The Super Research app lives
> at the deployment URL the dev shares with you (Google sign-in only).
> The app is required for this stage — `--pair` sits on its polling
> loop until you claim the code. Default window is 15 minutes.

Once the claim function writes the customToken, the BE exchanges it
via Firebase REST for `{refreshToken, idToken, uid}`, saves the
refresh token to the OS keystore, and prints
`[ok] Paired — you@example.com`. The `pollSecret` survives in
`research_config.json` so a future Reset Pair Code can rebind to the
same `deviceId` without a fresh handshake.

**`[2/6] On Startup` — supervised auto-restart prompt**
After the link lands, `--pair` prompts:

```
Enable On Startup? [Y/n]:
```

- **`Y` (default)** — opts into supervised mode; actual arming is **deferred to the Ready step** so an aborted login can't leave Firestore flagged as supervised while platforms are half-logged-in.
- **`n`** — skip; you'll run `python research.py --serve` manually after `--pair` finishes (and, on Linux/Mac, set up your own backgrounding via `nohup` / `tmux` / `screen` / your own systemd unit — see [§ Linux/Mac backgrounding](#linuxmac-backgrounding-stop-gap)).

**`[3/6] Discoverability` — who may find this computer**
*(Asked inside Stage 2 as an unannounced second question until 2026-09-17; it has its own step header now. Both answers still ship in one Firestore write — see the note at the top of this section.)*

```
Let other people find this computer and ask to use it? [y/N]:
```

- **`N` (default)** — private. Only people you hand the pair code to can ask for access. This is what an unattended or scripted pair records, deliberately: the default is the private answer, so a machine paired with no one watching is never published.
- **`y`** — the machine is listed, and people who do not have its pair code can find it and **ask** you for access. **It grants nobody anything.** You still approve every person by hand, and an approved person becomes an ordinary sharer with the ordinary sharer's powers — submit a topic to the fixed pipeline, nothing else. Whether the record itself can be read is unchanged either way: owner, sharers, and the machine, exactly as before.

⛔ **The write lands before the tick.** Both answers go up in that one patch first, and a refused write says so — `⚠  Could not save that — this computer stays private for now`, with `--visibility public` named as the retry — rather than ticking something that never reached Firestore.

Change it any time, from the machine:

```
python research.py --visibility public     # let people find it
python research.py --visibility private    # hide it again
python research.py --visibility            # print the current setting
```

…or from the app, in **Account → the Shared-with popup**, which writes the same field.

**`[4/6] API keys` — Anthropic + Gemini detect-prompt-verify** *(reordered to sit ahead of the browser logins on 2026-05-18 so CUA + Vision are available for Stage 5; shifted from 3/5 to 4/6 by the 2026-09-17 split)*
`--pair` runs `resolve_api_key()` and `resolve_gemini_api_key()` to check whether each key is already resolvable from any source (FE Account-page Firestore, Windows user-scope, shell env, or `.dg-supervisor.env`). For each missing key, it prompts:

```
Anthropic  — get one at https://console.anthropic.com/settings/keys
>  Paste Anthropic key (sk-ant-...) or [S]kip:
```

On paste, the BE makes a cheap **live-API verification call** (`models.list` for Anthropic; `GET /v1beta/models` for Gemini) with a 5s timeout. If the provider rejects the key (auth_failed), the prompt re-asks up to 3 times then offers `Save anyway? [y/N]` defaulting to no. If the verifier itself can't reach the API (network_error — offline pair, transient blip), the key is saved with a fail-loud-at-first-run warning rather than blocking the pair.

On verified paste, the BE writes the key to **BE-local persistence**: Windows User-scope env on Windows, `.dg-supervisor.env` upsert on macOS / Linux. It also mirrors to `os.environ` under the canonical name (`ANTHROPIC_API_KEY` for the Anthropic key, `GEMINI_API_KEY` for the Gemini key) so the running pair session can use the key immediately, and busts `_RESOLVED_KEY_CACHE` so the very next `resolve_api_key()` call (at the top of Stage 5 browser-login CUA init) sees the new key. Pair-time keys do NOT touch Firestore — the FE Account → API Config page is a separate surface that writes Firestore directly. (Pre-2026-05-23 devices may still have the legacy aliases `CUA_API_KEY` / `GOOGLE_API_KEY` in their User-scope env; `_migrate_legacy_api_keys()` runs once at startup, copies any surviving value to the canonical name, then retires the legacy entry. Idempotent + sentinel-cached.)

Skip is first-class per key — pair finishes regardless. Missing Anthropic falls back to **Playwright-only** verification in Stage 5 (less rigorous; no Pro-tier check) and surfaces a `cua_unavailable` alert at first job (recoverable via the chat-side `[Retry]` button once you add the key); missing Gemini silently disables narration.

**`[5/6] Browser logins`**
Runs the same real-Chrome sign-in engine `--login` uses:
- **Phase 1 — real Chrome sign-in.** Opens your *real, non-automated* Chrome (a plain subprocess) on the profile, pointed at the ChatGPT / Gemini / Claude / NotebookLM sign-in pages. You sign into each and solve any human-verification, then press Enter. Real Chrome is used here because Google BotGuard / Cloudflare block the automated browser on sign-in pages — and a human sign-in also *warms* the fresh profile's trust.
- **Verification is optional (2026-07-02).** Pair then asks `Skip the verification step? [Y/n]` — **Enter skips** (recommended: automated verify navigations on a brand-new profile are the strongest bot-score signal, and runs recheck logins at phase time anyway). Your per-platform state is still recorded truthfully via a local cookie read (zero page loads). Answer `n` to run the old patchright verify pass (sign-in + Pro tier per platform). `--login` never verifies — it's Phase 1 + the add-another-profile loop only.

The four platforms:
- ChatGPT (chatgpt.com)
- Gemini (gemini.google.com)
- Claude (claude.ai)
- NotebookLM (notebooklm.google.com)

When the optional verify pass runs and a platform is not-signed-in or on Free, an interactive prompt offers **[r]** reopen your real Chrome to fix (sign in / switch to Pro) or **[Enter]** continue as-is (keep Free / skip a missing platform). Verify also TOLERATES a Cloudflare / human-verification interstitial — it records "couldn't verify (likely still signed in)" instead of a false "not signed in". Ctrl+C cancels. The pair completes and the supervisor arms even on partial or zero logins — a login hiccup no longer blocks pairing.

> Phases 4 + 5 run in the frontend now (YouTube via Data API, Doc + email via Docs API + Resend), so YouTube Studio, Gmail, and Google Docs are no longer in the BE login checklist.

It mirrors the resulting login state to the BE-owned `devices/{deviceId}.logins` map so the app can show your progress.

> **Markers only tick after real auth.** `verify_login()` checks only auth-specific DOM (profile menus, account chips, chat-history lists). Generic chat-input elements are excluded because they show up on logged-out landing pages too.

> **F4 / DGOPS-7451 cookie check** *(relaxed 2026-05-18)*: when Stage 5 opens the browser, it inspects the Playwright profile for persisted Google auth cookies. The relaxed semantics: refuse pair only when the device was previously paired to a DIFFERENT account (`account_switch_with_prior_cookies`). First-pair on a fresh device OR re-pair to the same account both allow cookies through with a passive log line + `security_pair_allowed_with_prior_cookies` event — the existing Google session is presumed to belong to the user about to claim THIS link. Strict "any cookie → refuse" was creating a catch-22 with `--unpair` preserving the profile. For the account-switch refuse case, the message points to `--unpair --deep` (below) which wipes the profile cleanly.

**`[6/6] Ready` — arm supervisor (if opted in) + final message**
If you said `Y` at the **On Startup** step, the supervisor is armed now — Windows Scheduled Task, macOS LaunchAgent (`~/Library/LaunchAgents/com.dgresearch.supervisor.plist`), or Linux systemd-user unit (`~/.config/systemd/user/dgresearch-supervisor.service`) depending on platform. If you said `n`, any leftover scheduled task / launchd agent / systemd unit is torn down so the machine genuinely matches "unsupervised". Final banner branches on whether the supervisor is live.

### Step 4: After pair succeeds

Once the flow reaches the **Ready** step, it:

1. Closes the browser
2. Persists `pollSecret`, `deviceId`, `pairedUid` in `research_config.json`
3. Keeps the refresh token in the OS keystore (DPAPI / Keychain / libsecret)
4. Arms the supervisor inline if you said `Y` at the **On Startup** step (Windows Scheduled Task / macOS LaunchAgent / Linux systemd-user unit), or tears down any leftover scheduled task if you said `n`
5. **Exits the Python process — pair does not stay running.**

⛔ **Not "when all 4 platform logins clear"** — this line used to say that, and it contradicts the browser-logins step above: a partial or even a zero-login pair still reaches Ready, and the supervisor is still armed per your On Startup answer. The platforms you missed are signed in later with `--login`, and Phase 0 rechecks logins at run time regardless.

The final banner branches on whether the supervisor is live:

```
✓  Paired with you@example.com
✓  All 4 platforms logged in            (or "2/4 …" + a ⚠ row naming the rest, or "⚠  No platforms
                                         logged in yet" — the pair completes either way)
✓  1 browser profile — 1 concurrent run slot
✓  Browser closed
✓  Anthropic key saved to this machine  (or "Skipped — set later via Account → API Config")
✓  Gemini key saved to this machine     (or "Skipped — set later via Account → API Config")
...
The bond is forged.  The backend is live — running in the background.        # if supervisor armed
                                          OR
The bond is forged.  Start the backend in this terminal to accept jobs:       # if unsupervised
    python research.py --serve
```

### Step 5: Start the Server

```bash
python research.py --serve
```

The server runs on port 8000 with:
- A **5s heartbeat** → writes `devices/{deviceId}.lastHeartbeat` + `heartbeatAt` + `status` + `workerCount` so the app's Account page and sidebar device switcher show the right online/offline dot AND know how many parallel slots this device has. *(Two fields for one fact, deliberately, since 2026-09-16: `lastHeartbeat` is millis-as-int on **this machine's** clock — the FE's legacy mapper and the agent's REST reader both subtract it directly, so it can never become a Timestamp and is never retired. `heartbeatAt` is a Firestore `SERVER_TIMESTAMP` written **in the same atomic update**, one clock for writer and reader both, so a machine a minute fast no longer reads online forever after it is switched off.)* (FE offline threshold = **30s** = `DEVICE_OFFLINE_THRESHOLD_MS`, so six missed heartbeats flip the tile.) Worker-1 also publishes `version` / `updateAvailable` / `updateStatus` / `versionCheckedAt` (the app's Settings → About version + inline Check → Update control reads these) and `sourceCheckout` — `true` for a source tree (`git clone` + `python research.py`), gated on `_is_source_checkout()`, which is a **filesystem** test for the in-tree `agent/facade/__main__.py` (present only in a checkout, never in an installed wheel). It consults nothing on `$PATH`; this bullet used to call it "the PATH probe", which reads as the environment variable. The app then shows "Source checkout · update with `git pull`" (no Check button) instead of the app-update control.

  > ⛔ **THE RULE HAS TO ADMIT A KEY BEFORE THE WHEEL SHIPS IT.** `heartbeatAt`
  > rides the liveness update rather than the throttled publish, and that update
  > is **atomic** — so one key `firestore.rules` does not list 403s the whole
  > write, the `expireAt` cancel included, and a machine pairing inside the claim
  > function's 5-minute TTL would then lose its entire device document. Rules
  > first, wheel second, every time.
  >
  > ⛔ **AND NOTHING THAT NAMES A RUN GOES ON THIS DOCUMENT — wave 7.7E.**
  > `devices/{deviceId}` is read WHOLE by the owner, EVERY sharer and the machine;
  > Firestore cannot scope a read to fields. Every carrier of one account's topic
  > came off it: `queuedBehindTitle` is now deleted wherever it used to be
  > written, `_compute_global_queue_position` no longer extracts the topic ahead
  > (`behind_title` is always `""`), and the `queueOwners` entries the FE joins on
  > carry `uid` / `runId` / `position` and nothing else — the 60-character title
  > slice they used to include meant every person on a shared machine held a live
  > list of what everybody else was researching. This file had already written the
  > reason down and then done it anyway: the run-history publisher beside it
  > refuses to put history here because "one sharer would learn every other
  > sharer's run history".
  > ⭐ The removed KEYS stay on the rules whitelist: dropping a name from
  > `affectedKeys().hasOnly()` also refuses the write that would CLEAR it, and
  > machines on older wheels go on writing it until their owner upgrades. **The
  > invariant, for whoever adds the next field: if a sharer must not read it, it
  > cannot live here at all.**
- A **Reset-recovery watcher** — idle while the Firestore client is healthy; when the owner triggers Reset Pair Code, the BE's refresh-token revokes and this watcher polls `devices/{deviceId}/pending/{sha256(pollSecret)}` for the new customToken. On pickup it bootstraps a fresh keystore entry and exits cleanly so the supervisor respawns with new subscriptions. Net effect: Reset is hands-off on the PC under supervised mode.
- A **Firestore queue listener** — picks up jobs from `devices/{deviceId}/queue/`. Multi-worker aware: with `workerCount = N` (see § Multi-Worker below), N concurrent slots run in parallel; a new submit lands in explicit `queued` state only when ALL N slots are busy OR there are already-deferred queue docs ahead of it (FIFO fairness). Sharers can submit too — the BE picks up their queue items as long as their uid is in `sharedWith[]`. Cross-account submits sort by Firestore `submittedAt` (server timestamp, clock-skew immune); `_recompute_deferred_queue_positions` renumbers all deferred docs on every claim and cancel so the FE banner reflects #N changes live.
- A **command listener** for `stop` / `pause` / `resume` / `config` / `add_context` / `agent_decision` / `continue_anyway` / `retry_phase` / `skip_phase` / `skip_init_verify` / `retry_init_verify` / `skip_agent` / `retry_agent` / `continue_partial_agent` / `poke_agent` / `wait_longer_agent` / `dismiss_alert` / `discard_run` / `ping`, plus the owner-only worker-1 device commands `update` / `check-update` (the app-driven remote backend update: `update` runs the idempotent `_perform_self_update` + writes `updateStatus`; `check-update` re-checks PyPI and republishes the version fields). **Dispatcher resume-contract (2026-05-18):** every action that acknowledges a paused alert calls `_controls.request_resume()` so the pipeline doesn't stay paused after the user clicks the action button. A static-analysis test (`tests/test_dispatcher_resume_contract.py`) asserts the rule on every required-resume action and rejects accidental `request_resume` on non-pause actions (`pause`, `stop`, `discard_run`, `ping`, `add_context`, `config`, `dismiss_alert`).

- **CLI dispatcher pause-reason routing** (DGOPS-7710 / F6 + 3 follow-up fixes) — when an alert pauses the BE with a `pause_reason` (`agent_link_failed`, `human_verification_required`, `cua_unavailable`, `claude_chat_mode`, `login_required`, `pro_required`), the CLI `r` / `s` keystrokes route to the correct alert-specific helpers (`set_agent_decision`, `set_continue_anyway`, `request_skip_agent`, `request_skip_init_verify`) **plus** `request_resume`, so manual operator intervention always releases the pause. The same routing pattern is mirrored on the Firestore command bus.

- **Phase 2 Claude clarification auto-reply** — when a vague brief makes Claude respond with chat-text clarifying questions instead of starting Deep Research (signature: tail of last message matches "Once you ... I'll launch the research"), the polling loop auto-types `"Up to Claude to decide for the best output."` + Send so the agent proceeds without operator intervention. 5-condition heuristic (one-shot per agent) gates the trigger; see `_claude_asking_clarification` + `_claude_send_clarification_reply` near `poll_all_agents_round_robin`. Without this, the BE used to wait for an artifact that never appeared and eventually surfaced a generic "Hit a snag" alert at the wall-clock cap.
- A **local HTTP API** on `http://localhost:8000` for the CLI + any direct calls. ⛔ **Loopback only, and token-gated.** uvicorn binds `127.0.0.1`, not `0.0.0.0` (changed 2026-09-05), and since 2026-09-20 every route but `GET /api/health` requires the header `X-Super-Research-Token: <value of ~/.super-research/serve-api.token>` — a 0600 file minted at `--serve` boot, whose path (never its value) is printed by the boot banner and by `--help`. A `?token=` query parameter deliberately does **not** work; with no readable token file the gate fails **closed**. `POST /api/runs` takes its identity from the machine's pairing, not from the request body, and refuses a body that names a different uid. It had been reachable from the whole LAN with `allow_origins=["*"]` and **no authentication of any kind**, so anything on a coffee-shop wifi or an office network could read every run's meta, brief, agent markdown and podcast for **every account sharing the machine**, and `POST /api/runs` would start a run taking `uid` straight from the body. ⚠ The bind is not redundant now that the token exists — they are two layers, and neither has to be perfect alone.
- A per-run **log folder** + a published index of which runs this machine still holds logs for (per submitter), refreshed on the heartbeat; a **30-day retention sweep** (`LOCAL_LOG_MAX_AGE_DAYS`) that runs six-hourly on worker 1 rather than only as a side effect of the machine being used; and a periodic pull of the run's **cloud-side** P4/P5 log lines down into the run folder, so the collector — which is disk-only and allow-listed to `~/.super-research/logs/` — can ship them. All three feed `--send-logs` (see [Step 5d](#step-5d-hand-the-logs-over---send-logs)).

Keep `--serve` running while you use the app. If the server stops, the FE's heartbeat-based offline detection flips the device dot red at the **30s** threshold, and the per-phase silence watchdog (T1/T2 — see FE README → Watchdog) surfaces actionable dropdown alerts on each in-flight phase. The pipeline does NOT resurrect on reload if the heartbeat is stale.

**Queue persistence across restarts** — on `--serve` startup, the backend re-enqueues any `status:"queued"` researches from Firestore, so the queue survives a `--daemon-loop` respawn. Anything that was `status:"ongoing"` when the previous process died is flipped to `paused_backend_restart` (with a "Resume from checkpoint?" warn alert in the FE), instead of appearing live-but-frozen. If the persist itself fails (Firestore unavailable on respawn), affected researches surface a `paused_backend_restart_failed` red error with the actual error string.

### Step 5a (optional, recommended): Enable On Startup (supervised auto-restart)

```bash
python research.py --resurrect
```

Registers an OS-native supervisor that runs a **daemon-loop wrapper** — a tiny supervisor process that (re-)starts `--serve` whenever it exits for any reason: crash, stop button, logout, reboot, etc.

- **Windows**: Scheduled Task (`SuperResearchBackend`), ONLOGON + PT5M re-fire, `MultipleInstances=IgnoreNew`. Worst-case downtime: ~5s on `--serve` exit, ~5min on daemon-loop exit.
- **macOS**: launchd user agent at `~/Library/LaunchAgents/com.dgresearch.supervisor.plist`, `KeepAlive=true` + `ThrottleInterval=10`. Bootstrapped into `gui/$(id -u)` so Chrome gets the Aqua session.
- **Linux**: systemd user unit at `~/.config/systemd/user/dgresearch-supervisor.service`, `Restart=always` + `RestartSec=10` + `PassEnvironment=DISPLAY WAYLAND_DISPLAY XDG_RUNTIME_DIR` so Chrome can render in the graphical session. Requires `sudo loginctl enable-linger $USER` once — `--resurrect` probes and surfaces a WARN if Linger=no.

The Account page's **Indestructible** toggle reflects the real installed-task state, so the toggle survives unlink+relink. Turn it off from the same page if you ever want to stop auto-restart.

> **Cross-platform supervisor** — Windows uses a Scheduled Task; macOS installs `~/Library/LaunchAgents/com.dgresearch.supervisor.plist`; Linux installs `~/.config/systemd/user/dgresearch-supervisor.service` (run `loginctl enable-linger $USER` so the daemon-loop survives logout — the installer prints a WARN if linger=no but doesn't sudo-escalate). All three are first-class supported as of 2026-05-18. The Latin header (`resurgam · the backend rises`) fires on all platforms so you know the verb reached.

### Step 5a-ter (after an update): `--restart`

```bash
python research.py --restart
```

Cycles the running backend onto the code that is currently **on disk**. This is the missing step after ANY update route — `--update`, a bare `pipx upgrade`, or the superresearch.io installer all replace the package, but the live process keeps the old build in memory until it is restarted.

Deliberately **not** `--retire` + `--resurrect`: retire *removes* On Startup, so that pairing had people disabling always-on just to pick up an update. `--restart` keeps the pin and restarts in place (`launchctl kickstart -k` / `systemctl --user restart` / `schtasks /End` + `/Run`). With no supervisor installed there is nothing supervised to cycle, so it points at the manual `--serve` path instead of failing.

> Ordinary commands print a **restart-pending nudge** when the installed build and the serving build differ, so an update that arrived by any route can't sit silently applied-but-not-live. The nudge is skipped where it would be noise or wrong — `--serve` / `--daemon-loop` (they *are* the thing being restarted), `--restart` / `--update` / `--retire` / `--unpair` / `--resurrect` (they speak for themselves), and `--version`, which prints a richer variant naming both builds.

### Linux/Mac backgrounding (stop-gap)

`--serve` is a normal foreground Python process. To keep it alive past your shell session:

**Linux/macOS — `nohup` (lowest friction):**
```bash
nohup python research.py --serve > serve.log 2>&1 &
disown
```
Use `pkill -f "research.py --serve"` to stop. Log accumulates at `serve.log`.

**Linux/macOS — `tmux` / `screen`:**
```bash
tmux new -s superresearch
python research.py --serve
# Ctrl-b d to detach. Reattach with: tmux attach -t superresearch
```

**Linux — `systemd --user` (DIY alternative; native supervisor via `--resurrect` is preferred):**

The native supervisor (`python research.py --resurrect`) installs an equivalent unit at `~/.config/systemd/user/dgresearch-supervisor.service` automatically. Use this DIY ini only if you want to manage the unit yourself or pin a specific path:

```ini
# ~/.config/systemd/user/superresearch.service
[Unit]
Description=Super Research backend
After=graphical-session.target

[Service]
Type=simple
WorkingDirectory=%h/super-research-backend
ExecStart=/usr/bin/python3 %h/super-research-backend/research.py --serve --env-file %h/super-research-backend/.dg-supervisor.env
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```
Then: `loginctl enable-linger $USER && systemctl --user daemon-reload && systemctl --user enable --now superresearch.service`.

### Step 5a-bis (who can find this PC): `--visibility`

```bash
python research.py --visibility            # show the current setting
python research.py --visibility public     # let people find it and ask for access
python research.py --visibility private    # hide it again (the default)
```

Discovery, not access. A **public** machine is one other people can see listed and **ask** to use; you still approve each request by hand — **Review**, on the Account banner — and an approved person becomes an ordinary sharer with the ordinary sharer's powers (submit a topic to the fixed pipeline, nothing else). A **private** machine can only be asked about by someone you gave the pair code to. Machines paired before this setting existed are private, and nothing changes that on its own. Whether the device record itself can be **read** is unchanged either way: owner, sharers, and the machine, exactly as before.

The setting lives on the device record, so every surface agrees. ⛔ **Four writers set it, and `firestore.rules` names them by role rather than counting them — because the count has already been wrong twice:** the **owner**, from Account → the Shared-with popup; the **machine**, at pair time and from `--visibility`; the **chat agent**, which has its own Firestore door (`POST /device/visibility` — see [§ Super Agent](#drive-it-from-chat--super-agent-hermes--openclaw)); and **owner-unlink**, which deletes the field server-side on a hand-off. Only the first three meet the rule — the Admin SDK bypasses rules entirely — and all three are checked, because a constraint one writer can walk around is decoration. This § used to name two.

> **The field is being renamed `visibility` → `joinPolicy`** ("who may join this computer"). This backend **reads both names, old one first, and still writes only the old one** — because everything that ACTS on the setting reads `visibility` today (the app's public list queries `where("visibility", "==", "public")`), and a reader must agree with the writers, not with the migration's destination. Preferring the new name would treat its presence as proof of migration; on a toggle the cost of that disagreement is a door that never closes — write `visibility: private` while `joinPolicy` still says public, and the next read answers "already public". A machine carrying neither key (paired before 2026-09-04) reads **private**: absent is private, because the safe direction for a discovery setting is the one that hides.

### Step 5b (disable On Startup): `--retire`

```bash
python research.py --retire
```

The opposite of `--resurrect` — disables auto-restart while keeping this PC paired with your account. Three-step:

1. **Deletes the Windows Scheduled Task** so `--daemon-loop` won't auto-start at next logon / reboot.
2. **Kills every running `--daemon-loop` AND `--serve` process**, looping for up to 8s so a mid-enumeration respawn still gets caught (the supervisor respawns `--serve` every ~5s between deaths, so a single-shot kill misses any `--serve` that happened to be respawning at the wrong moment).
3. **Flips the Firestore `supervised` flag to `false`** so the Account toggle matches reality instantly.

Idempotent: works whether or not the task/loop was installed. Manual one-off `python research.py --serve` runs (role="other" in process discovery) within `DG_ORPHAN_MAX_AGE_HOURS` (default 4h) are NOT touched — only supervisor-spawned procs.

Turning off the **On Startup** toggle in the app → Account page runs the same teardown remotely.

### Step 5c (full disconnect): `--unpair` *(with `--deep` 2026-05-18)*

```bash
python research.py --unpair          # default: preserves the Playwright browser profiles (your platform logins survive)
python research.py --unpair --deep   # also wipes ALL browser-profile*/ dirs + pair-time API keys + worker state
python research.py --unpair --force  # wipe locally even when the server never confirmed the retire
```

The "I'm done with this PC" command — wipes everything `--retire` wipes, AND deletes the device server-side so it disappears from every browser instantly. After `--unpair`, this PC appears NOWHERE in the Super Research app's device list.

⛔ **The server-side delete is a GATE, not a step.** It runs at `[0/5]`, **before anything changes**, while the keystore is still alive: mint an ID token, `POST /api/devices/unpair-self` so the Cloud Function revokes the synthetic Firebase Auth user, deletes the device doc and drops the admin-only pollSecretHash entry. Everything below runs **only if that POST confirmed** — HTTP 200, or an HTTP 404 whose body is `{"error":"device_not_found"}` (the doc is already gone, so wiping locally is right). Anything else — a non-200, a network error, an exception, or an ID token that never minted — **changes nothing**, prints why, and exits **2**. Owner + sharer tiles vanish across every browser within a second of a confirmed retire.

> **Same endpoint, three branches — and only this one deletes anything.**
> `/api/devices/unpair-self` decides by the caller's relationship to the device.
> The BE calling as the synthetic device user (`--unpair`, above) gets the full
> **retire**. An **owner** pressing Unlink on a device tile in the app gets an
> **owner-unlink** instead: the device doc and this install stay alive and keep
> running, `ownerUid` is cleared and `sharedWith[]` emptied — and ⛔ **the access
> code is ROTATED first, as a precondition.** It has to be: the claim route
> grants OWNERSHIP to whoever presents a code against a device with no owner,
> which is exactly the state an unlink produces, so leaving the old code live
> would publish a claimable machine to everyone who had ever shared it. A
> rotation that fails **aborts the unlink** rather than proceeding. The new code
> comes back in that response and exists nowhere else, so an owner handing the
> machine on has to save it from that screen — the old one is dead the instant
> the call returns. A **sharer** leaving gets `arrayRemove` + a rotation for the
> same reason.

Then, five steps:

1. **Wipe local `research_config.json` + the OS-keystore refresh token** (DPAPI / Keychain / libsecret slot or the `chmod 0600` file fallback) + zero the in-memory caches. A respawned `--serve` now reads empty state and the heartbeat bails on its missing-deviceId guard.
2. **Process kill + scheduled-task / launchd / systemd-unit removal** — every daemon-loop and `--serve` process owned by this user.
3. **Report the retire** that step 0 already confirmed (or, on the `--force` path only, say plainly that it did not).
4. **Local artifacts summary.**
5. **Final-state verification** — if anything survived, prints the surviving PIDs so you can taskkill manually.

Exit code 0 means this machine was actually unpaired; **2** means it refused because the server did not confirm. `--force` restores the old wipe-anyway behaviour — see the note below.

**With `--deep`**, three more things go, and the README understated this for a while — it is not just one directory:

- **All** `~/.super-research/browser-profile*/` dirs (not only profile 1 — every profile added through pair Stage 5's multi-profile loop), plus **`workerCount` reset to 1**.
- **Pair-time API keys** — `ANTHROPIC_API_KEY` and `GEMINI_API_KEY`, plus the retired legacy aliases `CUA_API_KEY` / `GOOGLE_API_KEY` in case any survived the startup migration — from Windows User-scope env (HKCU) or `.dg-supervisor.env` on POSIX, and from this process's `os.environ` + `_RESOLVED_KEY_CACHE`, so the next `--pair` Stage 4 genuinely re-prompts and re-verifies instead of short-circuiting on a leftover key.
- **Transient multi-worker state** at the `queues/` root (`.worker.*.lock`, `_pending_queue*.json` and their `.tmp` siblings). Per-run history dirs under `queues/` are still preserved; the wiped files are recreated by the next worker's first job pickup.

Use `--deep` when re-pairing to a different account, or when the multi-account safety check refuses pair due to stale Google auth. The default preserves the profiles so a re-pair on the same account doesn't force you back through ChatGPT/Gemini/Claude/NotebookLM logins.

To bring this PC back: re-run `--pair` to mint a fresh deviceId + pair code and claim it from the app.

> **Also available:** `python research.py --unpair --force` wipes this machine even when the server never confirmed the retire. It leaves the device document and its Firebase login behind — remove the tile in **Account** afterwards. It is the only way to get `--unpair`'s orphan-process kill + On Startup removal when the server cannot be reached, and the escape hatch for a device record the retire endpoint will never authorise.
>
> **And:** `python research.py --uninstall` removes the installed package via pipx (detached, because pipx cannot delete the venv the process is running from on Windows). It **keeps** `~/.super-research/` — your logins and pairing survive — so run `--unpair` first if you want a full disconnect. On a source checkout there is nothing to uninstall and it says so.

### Step 5d (hand the logs over): `--send-logs`

```bash
python research.py --send-logs                      # consent screen, then send
python research.py --send-logs --select             # pick exactly which runs
python research.py --send-logs --runs 3             # the 3 most recent instead of all
python research.py --send-logs --yes                # skip the confirm (scripted use)
python research.py --send-logs --contact-email me@example.com
```

Packages this machine's recent logs and hands them to the team. It **shows exactly what leaves before it asks**, and it **always writes the local copy first** — so it still gives you something to attach to an email when the network is the problem. A local file is a success, not a fallback: the command exits 0 on it and prints the path.

What leaves, named one fact per line on the consent screen: at most `BUNDLE_MAX_RUNS` runs from this machine and only those from the last `BUNDLE_MAX_AGE_DAYS` days (both read from the bundle contract, 30 and 30 today); your research topics and the titles of what each run produced; links that open your research results (**anyone holding one can read them**); the email address on your account; what the agent screens showed while a run was working; this computer's hostname and the account name you sign into it with; and this device's own log files — the most recent few MB of each, **whatever their age**.

⚠ **Only the run count is what your choice changes.** The sessions are age-bound only, and the raw device-log tails have no age bound at all — and those tails carry the same topics, result links and account email for the machine's whole history. Lowering `--runs` does not mean "less of everything leaves".

What never leaves: **passwords, browser cookies or profiles, and your API keys.**

- **`--select`** prints a numbered list of what this machine actually holds and takes the names you pick; the count is then exact rather than a ceiling, and the age bound drops with it because it can no longer remove anything you chose. **Enter alone sends no runs** — just this computer's own log files, which is the whole evidence when a pairing failure produced no run at all.
- **`--runs N`** clamps to `[BUNDLE_MIN_RUNS, BUNDLE_MAX_RUNS]`; the collector sorts age-eligible runs newest-first and takes the top N.
- Each send mints an unguessable 8-char **support code** — it is also the object folder name, so it is the read capability for an upload no account owns yet. Everything under the bucket's `logs/` prefix is deleted **30 days after it arrives** (the lifecycle clock counts from the upload, not from when the index row was opened).
- Two **cooldowns**, read from a local file and never from Firestore (a rate limit that needs the network stops working exactly when the button starts being pressed): `SEND_LOGS_COOLDOWN_SEC` (10 min) **per sender uid**, over a shorter whole-machine floor `SEND_LOGS_MACHINE_FLOOR_SEC` (60 s). It used to be one unkeyed timestamp per OS user, which was fine only while exactly one person could press the button — a sharer sending no longer locks out the owner.
- The same thing is reachable from the app, which writes a `send-logs` / `send-logs-limited` / `send-logs-selected` device command. The **selection** is carried by a distinct action NAME rather than a new field on the old one, deliberately: a worker one release behind deletes a command it does not recognise and matches no dispatch branch, so the failure is "nothing left the machine" — pointing away from over-collection — instead of a build that ignores an unknown `runs` field and ships thirty when two were picked.
- **The chat agent's own log travels on its own**, with a support code of its own and its rotated copies included. It used to be sendable only inside a bundle from a research computer — and the two commonest reasons to be reading that log are having no computer paired and having one you cannot reach. See [`agent/README.md`](agent/README.md).

### Step 5e (what is actually broken): `--doctor`

```bash
python research.py --doctor
```

The first thing to run when something feels wrong. It is **platform-aware,
never destructive** — it never deletes user data, never unpairs, never touches
credentials — and it applies only safe auto-fixes (worst case: restart the
supervisor, and on Linux import the calling shell's graphical-session env into
the user-systemd manager). Six check groups: platform + pair state, browser
dependencies, supervisor unit / task, search path, process tree + port 8000,
and Linux `DISPLAY` propagation. It closes with a count of issues found and
auto-fixes applied, plus a de-duplicated list of manual steps (two findings can
legitimately prescribe the same command — a missing supervisor and a stopped
server both end at `--resurrect`).

**It says which of DNS / VPN / proxy / firewall is broken.** When the Firestore
client can't come up, `init_firebase`'s own reason decides the branch, and the
three are no longer conflated:

- **`transient`** → the network, not your pairing, and nothing here needs
  re-pairing. Doctor then probes four hosts — three Google API hostnames the
  pipeline cannot work without, and `api.anthropic.com` as a **non-Google
  control** — asking *resolution* and *connection* separately, because a name
  that won't resolve is DNS and a name that resolves but won't connect is a
  firewall or a proxy. `_network_verdict` turns those four results into ONE
  named fault (`no_dns`, `google_blocked`, `blocked_after_dns`, `partial`, `ok`)
  with a headline, actions, and the refusing IP addresses — which is exactly
  what a corporate IT ticket has to name. `google_blocked` (everything resolves
  except Google's APIs) is the corporate-resolver case this was built for. ⛔ It
  then says plainly that it **cannot change any of it for you** — DNS, VPN,
  proxy and firewall belong to your machine and your network. A diagnostic that
  implies it will fix a VPN is the same species of lie as the message it
  replaced.
- **`broken_install`** → part of the backend is missing; the network and the
  pairing are both fine. Before this branch existed, a half-written install
  classified as `transient`, so doctor printed "cannot reach Firestore", probed
  four healthy hosts, and concluded "the network path is fine" with an empty
  action list.
- **anything else** → credentials. The remedy comes from `credential_remedy`
  rather than an unconditional "run `--pair`", which is advice that spends the
  pairing you still have.

**Every run ends by offering to hand the logs over** — including `✓ Healthy`,
which is the case a person is most stuck in: they ran this *because* something
is wrong and the answer was that nothing here is. The line opens "Still stuck?"
and names [`--send-logs`](#step-5d-hand-the-logs-over---send-logs). It used to
be printed inside the one transient-network branch, so a machine whose Chrome
would not launch, whose supervisor was missing, or whose token was revoked read
a diagnosis and reached the bottom of the page with nothing to do next.

⛔ **Doctor does not install anything for you.** The browser check runs the same
headless `channel="chrome"` launch probe that pair Stage 5 does, but on failure
it only prints `patchright install chrome` (and, if Chrome itself is absent, the
OS-appropriate install one-liner) as **manual** steps. Auto-fetch is `--pair`'s
job — see [Before you start](#before-you-start-prerequisites-checklist).

### Step 6: Fire a research topic in the app

Open Super Research (the web app) → type a topic → backend picks it up from Firestore → pipeline runs here. If the app says "No backend connected" there's a Connect bubble with a Scan QR button that links in seconds.

## Multiple Devices (same user)

One account can pair multiple PCs. Each `--pair` on a new machine mints its own synthetic device user + top-level `devices/{deviceId}` doc. The app's sidebar gets a device switcher (with online/offline dots) and every research is stamped with the device it ran on — so jobs you fire from the app route back to the specific PC that was **active** when you hit Start. If you fire two jobs on the same device while it's at capacity, the second queues; if you fire one on a different device, both run in parallel.

## Multi-Worker (parallel runs on one PC)

A device can run **multiple pipelines in parallel** when its backend has `workerCount > 1` in `research_config.json`. Default is **1** (single-worker); a typical multi-profile production setup is **2**. Each worker is a separate Python subprocess spawned by the daemon-loop supervisor on adjacent ports (8000, 8001, …); each subscribes independently to the same `devices/{deviceId}/queue/` and `devices/{deviceId}/commands/` subcollections, and each pins to its own browser-profile dir (`~/.super-research/browser-profile-N/`) so they don't race on the same Chrome session.

- **Where it's set:** `research_config.json.workerCount`. Loaded by `load_worker_count()` with a >=1 clamp so a bad config can't disable the only worker. Note the heartbeat publishes **running** capacity (`_running_worker_capacity`), not the configured profile count — a foreground `--serve` on a 2-profile device runs one worker and used to advertise two, which is why a second submit stalled at Phase 0 instead of queueing.
- **How to raise it:** run `python research.py --pair` and at the "Add another browser profile?" prompt during Stage 5, add a second profile. The BE will spawn the additional worker on next supervisor cycle.
- **Where the FE learns about it:** every heartbeat publishes `workerCount` on `devices/{deviceId}`. The FE gates a new submit on `ongoing >= workerCount OR queued > 0` to decide ongoing vs queued.
- **Two researches running at once on one PC — is that a bug?** No. It's the expected behavior under `workerCount=2`. The queue only kicks in when ALL workers are busy.
- **Cross-cutting safety:** the on-disk worker lock (`queues/.worker.{N}.lock`, one flat file per worker — `_worker_lock_path`) prevents dual-spawn on supervisor restarts; the listener `_pending_enq` counter prevents back-to-back claims by Firestore listener replay; a pre-claim status re-check drops a claim if the research doc transitioned to a terminal status (cancel, stop) between claim-scan and enqueue (cross-worker cancel race guard).
- **HARD_RESET safety:** Reset Pair Code writes a single `hard_reset` command to `devices/{deviceId}/commands/`. Every worker subscribes and processes it independently — each touches `.stop` on its own active run dir, flips its own active research doc to `cancelled`, and schedules `os._exit(0)` so the daemon-loop respawns it clean. No zombie runs across N workers.
- **Worker rest/wake (#903):** the owner can park an idle worker from the app's Shared-With popup, recorded in the owner-writable `devices/{deviceId}.restingWorkerIds[]` field. A resting worker takes **no new runs** — `_worker_is_resting()` gates both new-claim paths (the start-listener claim and the idle-rescan claim; fresh device-doc read, ~3s TTL, fails open to awake). In-flight runs finish untouched (resumes bypass the listener). When all workers rest, new submits queue with a "Workers paused" state; it persists across BE restarts (the 12h stale-queue sweep exempts rest-deferred docs). Sharers never see worker pills.

## Multiple Users (same backend) — sharing via pair code

The same 8-char pair code drives sharing. Show the code under **Settings → Manage devices** (or copy it from the email after Reset), share it with a teammate, and they paste it into their own **Account → Pipeline Connection**. The FE claim function notices the device is already owned and appends their uid to `sharedWith[]` — they get a tile labeled "Shared by {your name}" and can submit research that runs on your PC.

Per-user scoping is enforced by Firestore rules + the BE's custom claim. Sharers can submit research and read their own runs; they can't read the owner's other data and can't read the owner's research history. Reset clears `sharedWith=[]` in one step — handy for revoking access to a stolen / overshared device without taking the BE down.

⛔ **And a sharer cannot see the code — but not for the reason this paragraph
used to give.** It said the code was "gated by the owner's Pair Code Lock if
enabled", which described the pre-fix model as if it were the boundary. It was
not: the code was a field on `devices/{deviceId}`, the FE's listener mapped it
into client state for every device it returned, shared ones included, and the
only thing between a sharer and it was a **render condition**. The PIN gated a
`setState` over a value already sitting in their browser. What actually
protects it now is that the value is **not there**: it lives in the admin-only
`_internal/device_secrets/entries/{deviceId}` (`allow read, write: if false`
for every client — see [§ Pairing model](#pairing-model-no-json-keys-to-copy-around)), and the only way to get it is the
owner-gated `POST /api/devices/pair-code`, which checks **ownership** and
answers a sharer with the same `403` as a stranger. The Pair Code Lock PIN is
a client-side reveal gate on top of that, not the access control — and it is
real now precisely because the value is no longer in the browser until
somebody asks.

**Sharer keys (#938) — cost follows the submitter.** A sharer can save their OWN Anthropic/Gemini API keys for a computer shared with them (Account → API Config lists the shared computers alongside owned ones). Those keys are used **only for the research the sharer submits** on that computer — resolution is submitter-aware (sharer's device key → owner's device key → owner legacy map → owner flat → env), so the owner keeps a **byte-identical zero-change path** and never pays for a sharer's runs. The owner never sees a sharer's key value, only a small **key-glyph** beside any sharer who has supplied one (server-computed — the owner can't read a sharer's key doc). A sharer with no per-device key of their own simply falls back to the owner's chain (unchanged behavior).

Each key lives in its own document at `users/{uid}/deviceKeys/{deviceId}`, and a computer may read only the one named after its own `deviceId` claim. The key a sharer gives a machine does reach that machine — that is what running on it means — but nothing else in their account does. Before this the keys were a `byDevice` map inside `settings/prefs`, so picking one out meant reading the whole document: every key they had saved for every computer, their access-code-lock hash, their delivery address. A key still sitting in the old map is copied across on the sharer's next sign-in.

## Pipeline Phases

| Phase | Platform | Typical Time |
|-------|----------|------|
| 0. Init | System (browser launch + login check) | ~10s |
| 1. Brief | ChatGPT Pro + latest thinking model | ~25 min |
| 2. Research | ChatGPT + Gemini + Claude (parallel) | ~49 min |
| 3. Podcast | NotebookLM (upload + audio generation) | ~25 min |
| 4. YouTube | FE-owned: Data API (ffmpeg encode + `youtube.videos.insert` via OAuth) | ~1-2 min |
| 5. Report | FE-owned: Docs API + Resend | ~3 min |

Times based on real run analytics. Total: ~1h 50m for a full pipeline. ChatGPT Pro, Claude Pro, and Gemini Advanced are the assumed baseline — see [Before you start](#before-you-start-prerequisites-checklist) for per-seat costs. Non-Pro accounts are flagged with `[Continue with Free] [Retry]` — by the in-phase tier tells by default (verification is opt-in since 2026-07-02), or by Phase 0's vision check when that Setting is on; Retry re-checks after you sign in with a Pro account in the same browser. If you `Continue with Free`, the pipeline runs end-to-end on Free tiers, but Deep Research depth, image quality, and turn limits are far lower than what the per-agent timings, prompts, and waits were tuned against, so per-agent output is much shallower.

## Phase + per-agent narration (consolidated 2026-04-30)

Long quiet stretches in Phases 1–3 are expected (ChatGPT Pro thinks for ~3 min before writing, NotebookLM renders for **5–10 min on Short, 10–20 on Default, 30–45 on Long** mode — `_AUDIO_TYPICAL_RANGE_MIN` in research.py drives the in-chat ETA narration), but a dead-looking tile makes the whole app feel broken even when nothing's wrong. The narration system was consolidated 2026-04-30 from four overlapping writers down to a single per-agent narrator with a backend-fallback tail. Result: cheaper, less duplication, less parroting.

- **Per-agent narrator (the only writer now)** — every Phase 1/2 agent has a narrator worker that reads a bounded ring buffer of recent events (~50) and emits a `phase_narration` / `agent_narration` event about every 6s per active agent. Brain (primary swapped 2026-05-28): **Gemini Flash** primary (`gemini-3.8-flash` as of 2026-09-17, env `GEMINI_TEXT_MODEL`); **Anthropic Haiku 4.5** cross-vendor fallback (`claude-haiku-4-5`, env `DG_NARRATOR_HAIKU_MODEL`) on any non-429 4xx/5xx/timeout/empty response. 429 is surfaced to the outer loop for backoff rather than absorbed by the fallback. The swap consolidates the narrator onto the same text-task stack as summary / title-fallback / URL-extractor (was the lone Anthropic-text-call outlier); Haiku stays as the hedge for Google regional blips. Pre-04-30 used Gemini Pro 2.5 (parrot issue at temp 0.2 — fixed on 3.5 Flash). Cost envelope: ~200 input / 30 output tokens per call → <$0.02 per full pipeline run.
- **Anti-parroting prompt + chrome scrub.** The narrator system prompt (in `_narrator_loop`) has explicit anti-pattern rules: don't echo input verbatim, don't start with "currently" or "Status:", skip chat-thread chrome (`You said:` / `<name> responded:` / `brief.md`). Above the narrator, `_compact_event_for_narration` scrubs those same chrome strings out of the input window BEFORE the narrator sees them — scrape outputs (chip / step counts) are untouched.
- **DOM scrape rules per platform:** Claude scrape (`scrape_progress_claude`) is panel-scoped to `aside` / `[class*="artifact"]` / `[class*="research"]` — dropped `.font-claude-message` and `.contents` heading selectors that grabbed conversation-chrome, with a belt-and-suspenders `you|claude|chatgpt|… said|responded` filter behind them. ChatGPT P2 panel walker (`scrape_chatgpt_activity_panel_tracking`) dropped the loose `[class*="row" i]` selector and gates rows on `VERB_GATE` with min-length raised 4→12 to drop "OK" / "Done" single-word noise. ⚠ `VERB_GATE` is **no longer a fixed verb allowlist** — #922 (2026-07-08) replaced the 23-verb list with a leading-**gerund** test (`/^[a-z]+ing\b/i`), because the allowlist was rejecting real step titles like "Creating a brief on…"; a `COUNT_CHIP` regex sits beside it to drop "Searching 1 website", whose number changes every poll and would churn the list.
- **Vision narrator (`narrate.py`) RETIRED.** `PHASE_BUDGET=0` by default — the per-agent narrator covers the same slot via DOM events without burning a separate Gemini call. Set `DG_VISION_NARRATE=1` to re-enable it as a coverage escape hatch.
- **BE phase-fallback tail.** When the narrator is silent (Gemini + Haiku both failing, or 6s startup gap), the `is_et` branch inside `poll_until_done` emits a per-agent status tail — `Extended Thinking active · 12,400 chars drafted` (ChatGPT), `Thinking active` (Claude), `Planning active` (Gemini) — into `progress["progress"]`. *(All three are built the same way, `f"{_think_label} active"` with an optional `· N chars drafted`; the Claude and Gemini renderings were quoted here as a bare label plus an ellipsis, which matched neither the code nor their own neighbour in this sentence.)* The FE renders this as a final tail under the agent narration. *(These are load-bearing DOM/status matchers, deliberately kept when #955/`01a7248` dropped "Extended Thinking" from user-facing narration copy. Claude's label became plain **"Thinking"** on 2026-07-30, because Opus 5 dropped that toggle and naming it advertises a control the user cannot find.)* No more dead silence on a working agent.

> **Narration brain envs:** `DG_NARRATOR_USE_GEMINI` (default `1`; set `0` to skip Gemini and go straight to the Haiku fallback — renamed from `DG_NARRATOR_USE_HAIKU` on 2026-05-28 when the primary swapped, with the old name honored as a backwards-compat alias for one release), `GEMINI_TEXT_MODEL` (default `gemini-3.8-flash`, also drives narrator primary), `DG_NARRATOR_HAIKU_MODEL` (default `claude-haiku-4-5`, the cross-vendor fallback), `DG_VISION_NARRATE` (default `0`; set `1` to re-enable the retired vision narrator). All optional.

## Phase 0 verification (OPT-IN since 2026-07-02)

**Login verification is off by default for every account** — proactive verify navigations are the strongest bot-score signal on fresh profiles (live evidence: a verify pass sailed through and the Cloudflare challenge hit the *work* page seconds later). Turn it back on per-account via Settings → Pipeline → "Verify sign-ins before each run" (`verifyLogins`). What replaces it:

- **Phase-time cookie trust** — before each phase touches a platform, a local cookie read (zero page loads) confirms the profile still holds that platform's session cookie. Cookie present → trusted; genuinely missing → the full tab+vision gate + `login_required` card runs, exactly as before.
- **Stale-cookie honesty** — a session that died server-side (cookie present but invalid) is caught by the phase's own failure paths, which now probe the already-open page for a login wall and surface an actionable "looks signed out" card (never the old generic "didn't start"); that platform is then re-verified for real on Retry.
- **Tier tells without navigation** — ChatGPT: the P1 Pro-selector backstop; Gemini: a DOM tier read on its P2 work page; Claude: the chat-mode card (Free Claude lacks the Research tool).

When verification IS enabled, preflight walks platforms one at a time (tab open → 4s hydration → URL check → CUA vision → per-platform `login_required`), exactly the 2026-04-24 sequential design.

**The Google credentials Phases 4 and 5 run on are checked here too — before the work, not after it.** `_probe_google_credentials()` asks the app's `/api/health/google` at the top of Phase 0 and logs **one line either way**, healthy or not (logging only on failure leaves "3 of 3" and "never ran" identical in the record). ⛔ It runs **above** the `skipInitVerify` blanking, like the CUA key probe: a dead credential is not a login nicety. The two halves are treated differently on purpose —

- **Phase 5's Doc + email identity is pinned** (a document has to land in ONE Drive, so nothing can rotate around it). A rejection there **fails Phase 0** with an `oauth_expired` card and pauses, because starting would do all the research and then fail at the last step.
- **Phase 4's upload pool is reported, never blocked on.** One live slot still uploads, and stranding a whole run over a degraded pool trades a real research result for a warning; a partial pool logs a WARN naming which accounts were rejected and why.

*(This is the 2026-09-03 fix. Both phases had been skipped by the preflight on the note that they are "FE-owned … neither needs login verification in the BE preflight" — true of a browser login **walk**, and read for four months as needing no check at all. That day a run did the research, wrote three reports, encoded and uploaded a podcast, and discovered at minute 40 that it could not create the document.)*

## Phase 2 — the report is the artefact (Aug 28)

⛔⛔ **THE PER-PLATFORM SHARE-LINK RULES DESCRIBED HERE WERE REMOVED ON
2026-08-28 (stretch 6.6B), AND THIS SECTION DOCUMENTED THEM AS A LIVE,
HARD-FAILING CONTRACT.** It said Gemini and Claude were **"PUBLIC share links
ONLY, hard-fail on miss"** with "a Retry / Skip gate" — a completion rule that
had not been true for months and is now not even implementable: the three
extractors, the `_PUBLIC_SHARE_*` authority and the CUA fallback are gone. An
auditor reading it would have concluded Phase 2 can fail on a link. It cannot.

**What Phase 2 actually does.** It completes on the MARKDOWN: `n_chars > 0 and
md_saved`. The report is saved to `documents/<agent>.md`, mirrored to the
Firestore `documents` subcollection, and the FE is handed the in-app
`/documents?open=…` link as the agent's primary — the only link `PhaseDropdown`
renders for P1 and P2. The conversation URL is captured with `current_url()` for
resume and for the P2→P3 NotebookLM handoff; it is never a gate.

**Why the share step went.** Measured over 45 agent-legs across ~15 real runs:
2.2 minutes and 21.7 CUA calls per run — 31% of every CUA call the pipeline
makes — for a link nothing gated on, which on a large share of runs was the
private conversation URL fallback anyway. Delivery now uses Super Research's own
`/shared/doc/{id}` snapshot pages, minted from the markdown already in
Firestore, which open for a reader who is not the owner.

`link_extracted` is still emitted per agent the moment the in-app primary lands
(no phase-end batching).

**Images inside the extracted document are kept (wave 4).** `html_to_markdown`
no longer throws pictures away — decorative ones are dropped, the rest survive
into the markdown. Every extracted document (the brief, the three agent
reports, regen and retry saves, `consolidated.md`) then passes **one rewrite
before any save**: `_rehost_document_images` fetches each image **once per
research**, hands the bytes to the web (`POST /api/document-images`), and
rewrites the reference to the path the web returned —
`/document-images/{researchId}/{sha256}.{ext}`. Anything not kept becomes a
bare `![alt]()`, so a caption never silently turns into a broken hotlink. The
contract lives on the FE side in `src/lib/document-images.ts`; the Claude panel
tracker keeps its old image-free output on purpose.

The fetch is deliberately hostile to the network it is reading from: **https
only, cookie-less, no proxies or `.netrc`** (`trust_env = False`), **every
resolved *and* connected address re-checked as public** — the peer is verified
after connect and before TLS, because a redirect or a DNS rebind can move it —
redirects re-checked (`_DOC_IMG_MAX_REDIRECTS = 3`), a streamed **5 MB** cap, a
magic-bytes raster sniff (never the served Content-Type), tiny images dropped
(`_DOC_IMG_MIN_PX = 48`, decorative `≤ 32`), **40 per document**, a per-image
and a per-document time budget, all of it off the event loop. The
`User-Agent` carries no product name — the host is whatever a platform's answer
linked to, and a prompt a sharer wrote can choose it, so it learns the IP and
the time and not whose. The log gets **counts only**.

**Claude 2-artifact wait hard-fail.** If Claude has reached ≥80% of its allotted wait time AND has <2 artifacts in the side panel, the pipeline hard-fails that agent with Retry / Skip — no silent half-answer. First artifact is almost always a research plan, not the final report; accepting a single-artifact Claude as done produces a broken downstream.

**Tab round-robin — `target_page` anchoring.** `agent_loop` accepts a `target_page=None` parameter. Before every polling tick it calls `bring_to_front()` on that agent's tab so CUA always sees a live browser viewport, not a stale background capture from whichever tab happened to be front when three agents were racing. `_anchored_screenshot()` helper handles the pattern; re-anchors after every `execute_action` too. Prevents cross-agent tab interference — e.g. Gemini's vision call returning Claude's screenshot because Claude's tab happened to be front-of-stack when the capture fired.

**Claude setup via Playwright (not CUA).** `setup_claude_dr` was rewritten as Playwright steps — first ensure the composer is on **"Chat"** (not "Cowork") mode, then pick the **highest Opus row the account is offered** from the model dropdown (no version literal — `P2_MODEL_POLICY["claude"]`, see [Before you start](#before-you-start-prerequisites-checklist)), set Effort = Max, enable the Research tool — all DOM selectors + `.click()` calls. *(The Thinking toggle step — "Adaptive Thinking", Step 1D — is **policy-gated off** since 2026-07-30: Opus 5 removed the separate toggle that Opus 4.x carried inside the Effort submenu, so effort IS the reasoning lever now. The step is kept, not deleted, because `thinking` in the policy dict re-arms it in one value if a future model reinstates the control. While it was armed it opened the model popover on EVERY run to reach a control that no longer exists — the second model-menu interaction users reported as "it opens the model selector twice".)* Eliminates ~30-90s of CUA vision overhead per setup and removes a class of "CUA clicked the wrong thing" setup failures. CUA is still used mid-run for anything that isn't deterministic DOM.

**Clipboard permissions — granted once at browser bootstrap, covers every P1/P2 agent.** The pipeline drives the clipboard for two things: brief *delivery* (`verified_paste_brief` Strategy A pastes via `navigator.clipboard.writeText` + Ctrl+V — Phase 1 brief and Phase 2 brief hand-off) and report *extraction* (Gemini's "Share & Export → Copy contents" writes the report markdown to the clipboard for the T1 tier; ChatGPT/Claude copy paths likewise). In the automated patchright context those clipboard APIs are **denied** unless the permission is granted, and the denial is silent — the page still shows a "copied" toast but the read comes back empty, so Gemini T1 falls through to the T2 DOM scrape on every run. To cover all agents in one place, `Browser.start` grants `clipboardReadWrite` + `clipboardSanitizedWrite` once at browser bootstrap via CDP `Browser.grantPermissions` (`_grant_clipboard_permission`). The grant has no `origin`/`browserContextId`, so it applies to the persistent context and persists for the session — every agent tab (`new_tab` and `open_isolated_tab` share this one context) inherits it. `verified_paste_brief` still grants per-paste as a defensive fallback in case the bootstrap grant ever fails.

## Sources + citations (per run)

Every Phase 1/2 agent's sources are collected during the run and turned into a
numbered bibliography on the way out. This subsystem went undocumented here for
its whole life; what follows is the part a maintainer has to know before
touching any of it — and nearly every ⛔ below is a defect that shipped because
the rule was not written down anywhere.

**Where the URLs come from — three readers, unioned, never replaced.**

- **The live panel scrape.** Each agent's DOM walker publishes `source_urls`
  (and `source_items`, `{url, title}` rows) onto `progress`, and every merge is
  a **union in document order**, not a replace — a re-scrape may return a
  different subset or ordering, and a strict `>` count test would throw away
  URLs that are objectively new. ChatGPT's Deep Research collapses its **Cited
  sources** panel by default and does not render the `<a href>` nodes until it
  is opened, so the scrape clicks it (guarded on `aria-expanded`, opt out with
  `DG_SOURCE_PANEL_EXPAND=0`) and re-scrapes after a 1s lazy-render beat; a
  pre-click scrape typically saw 0–3 where the panel held 10–20.
- **Claude's sources disclosure, pressed once per run.** `read_claude_sources_panel`
  presses it at the point the run is done and always returns an `outcome` —
  `absent` / `disabled` / `already_open` / `opened` / `press_failed` /
  `read_failed` — rather than a bool, because "no rows came back" and "the
  control never expanded" need different answers. ⭐ "It opened" is read from
  the control's **own** `aria-expanded`, never inferred from "the scrape
  returned data" (#914 paid for that distinction on this exact panel). The
  latch lives on the phase dict, so *once* means once per **run**, not once per
  process — `--serve` runs many runs in one process. ⛔ It is called from
  **both** extract sites, the Playwright-confirmed-done path and the
  CUA-confirmed-done path, and must run **before** `extract_claude_response`,
  which closes the artifact panel as its first act.
- **Vision, as a supplement only.** `extract_source_urls_via_vision` reads the
  side panel when the DOM misses URLs (collapsed rows, popovers, lazy content,
  anchor-less click targets). Confidence `< 0.4` returns nothing; a response
  clipped at the token ceiling is **salvaged** for the URLs that reached their
  closing quote rather than discarded whole (returning nothing is how the
  activity panel lost 56% of its sources on one run). Disable with
  `DG_VISION_URL_EXTRACT=0`.

**One host filter, `_is_platform_host`, and it is a suffix test.** A source list
must exclude the agents' own pages, and this went wrong in two directions
before it was centralised:

- ⛔ **It tests the HOST, never the URL.** ChatGPT appends
  `?utm_source=chatgpt.com` to **every** outbound source link, so a substring
  test written to skip the platform's own pages was instead deleting every
  genuine source it saw — measured on one captured panel, 22 of 40 anchors
  dropped, 16 sources reported where 36 existed. That was diagnosed once,
  repaired at one of **ten** sites, and the other nine kept the substring test
  for another month. The scrapes run in JS and cannot import the Python list, so
  `_js_platform_guard()` emits the same rule inlined per site and a test asserts
  every site matches it byte for byte.
- ⛔ **`_HOST_DENYLIST` lists PRODUCT SURFACES, not vendors.** It briefly held the
  bare domains `openai.com` and `anthropic.com`, which dropped
  `anthropic.com/research/…`, `openai.com/index/…`, `docs.anthropic.com` and
  `platform.openai.com` — the vendors' own published research and documentation.
  A run whose topic is one of those companies, or LLMs at all, would have had
  its most relevant citations deleted for naming the wrong host. The rule is
  "this page is the agent talking to itself", not "this company made the agent".
- Membership is `h == d or h.endswith("." + d)`, anchored on a label boundary —
  an exact-equality test answered False for `support.anthropic.com`, which is
  how an Anthropic help-centre page was presented to the owner as a research
  source, and `notchatgpt.com` is not swallowed by `chatgpt.com`.

**The cap is `_SOURCE_LIST_CAP = 200`, and it is head-first.** Panel order is
roughly relevance order — the head is the evidence, the tail is where the search
drifted — so the direction stays head-first and the ceiling is what moved. 200
URLs is ~20 KB against Firestore's 1 MB document limit. ⚠ The JS walkers carry
the literal because they cannot import it; `tests/test_source_cap_0806.py` is
the only thing keeping the two sides in step.

**From URLs to a bibliography.** After each agent's markdown is written:

- `_sweep_source_urls` collects every URL the report actually cites, and
  `_number_document_sources` adds an inline `[n]` marker at each cited sentence
  plus a trailing `## Sources` list. `_document_with_sources` is the write-site
  face; it never raises, because an un-numbered document is a smaller loss than
  a lost one.
- ⛔ **Code spans are MASKED, not stripped.** A report that shows you
  `curl http://localhost:8080/api` is teaching, not citing — the owner's
  screenshot of an agent card listing ninety-seven "sources" whose visible
  twelve were `127.0.0.1`, `localhost` and a bare backtick is what this closes.
  `_mask_code_spans` blanks fenced and inline code **to spaces of the same
  length**, keeping newlines, because `_extract_findings` locates each snippet
  with a literal `md.find(url)` on the original text and deleting bytes would
  slide every offset after the first code block. Fences are masked before
  inline, since a fenced block can contain single backticks. It returns the
  spans as well as the mask: a position derived from masked text is not
  automatically a position outside code.
- `_extract_findings` returns `{url, snippet, sourceTitle}` rows — candidates
  are the **union** of the panel list and the report's own URLs (markdown-link
  targets plus bare), deduped on a normalised key so `?utm_source=…` doesn't
  make one page into two, ordered by **first mention in the report**, capped at
  12 per agent. Taking candidates from the panel alone returned `[]` for a
  Claude report carrying forty markdown citations, and the 12-cap then took the
  first twelve *panel* rows whether or not the report cited them.
- The marker is an ordinary markdown **link** whose text is `[n]` — not a GFM
  footnote — so tapping the number opens the source instead of scrolling to the
  foot of the page. Numbers ascend through the document. The bibliography
  heading is level **five**, and an alternate title is used when the report
  already ends with a sources list of its own (deep-research reports commonly
  do, and two identical `Sources` headings show up in the document, the share
  and the delivered Google Doc). `_strip_numbered_sources_section` cuts our own
  tail back off before `save_meta` analyses the report's structure, so that
  reader stays byte-identical to what it saw before numbering existed.
- ⛔ **The brief is deliberately NOT numbered.** `_DOC_SOURCE_MARK_RE` is the
  idempotency sentinel, and `brief.md` is the file ChatGPT and Claude
  *receive* — numbering it handed the agents our own sentinel, and one imitated
  marker in a report made the whole pass a no-op on it: no numbers, no
  bibliography, no log line. The sentinel cannot be made un-echoable, so the
  input is what changed. Otherwise the pass is idempotent and bails at DEBUG on
  a document that already carries markers.
- The run-wide bibliography for **generated** documents is the FE's half
  (`src/lib/doc-sources.ts`): numbering there is stable and model-independent,
  computed from the persisted agent rows — ChatGPT, then Gemini, then Claude,
  each in first-mention order, deduped on a normalised URL — **before** any
  model call, so a section prompt can be handed "you may cite 4, 5 and 9" and a
  re-generation produces the same bibliography. A marker it cannot resolve is
  deleted from the prose rather than left as a numeral that links nowhere.

**What lands in meta.** Per agent: `sources` (count), `sourceUrls`, `findings`
(falling back to the first three section headings when the extractor returns
empty), `observedSources`, and ⭐ `sourceHostCount` — the panel rows that named
a **domain** and carried no link. Nonzero beside `sources: 0` is the difference
between "Claude cited nothing" and "Claude cited eight sites we could not turn
into URLs", which is exactly the distinction the zero-source investigation
needed and did not have.

## Per-phase alert narration

Every failure category — timeouts, CUA fallbacks, Anthropic 429/529 retries, share-link misses, login-expired, ffmpeg failures, email auth problems, browser crashes, and more — emits into the correct phase's `PhaseAlertPanel` inside the app's phase dropdown. No chat-bubble spam. Per-phase coverage:

- **Phase 0** — browser launch/crash, Playwright profile lock, missing Chromium binary
- **Phase 1** — brief timeout, brief paste retry per attempt, brief-short (offers `continue_anyway`), brief model error, manual-brief 3h backstop (auto-fail with `pipeline_stopped` reason `manual_brief_wait_backstop_3h`)
- **Phase 2** — agent timeout (auto-skip with partial save if ≥200 chars; no human prompt needed since 2026-04-30 `be8f7b3`), send-button CUA fallback, paste outer-retry narration. **Cloudflare / human-verification is hands-off AND non-blocking** (#955 Gap #1b, `115fe71`): passive detection only (zero interaction with the walled tab) and P2 **no longer pauses** on it — the old blocking `wait_for_verification_clearance` / 600s tier-5 poll was dropped for P2 (the wall sets `_controls.hv_blocked[agent]` and hands to `_hv_setup_fail_card`), so siblings 2B/2C keep starting the moment the wall is hit and one agent's card never freezes the round-robin (non-blocking parked-decision resolver, #953). With the L3 auto-skip toggle ON (default), the walled agent is greyed + its tab closed on the hands-off deadline (`HANDS_OFF_AUTO_SKIP_SEC=300`, ~5 min); off = a **Skip-only** `DecisionCard` (Retry omitted — it would only re-navigate a walled account; unified across ALL walls). Clear it by signing into that platform in real Chrome between runs. (P1/P5 still use the shared *blocking* single-surface verification wait.) Browser crashes emit a passive banner (`emit_browser_recovery_status`) and no Retry/Skip prompt — see the copy note under [§ Stuck-state risk fixes](#stuck-state-risk-fixes-2026-04-30-6545335--be8f7b3--549f079) for what that banner may and may not claim.
- **Phase 3** — NotebookLM **notebook-link** extraction failure (Retry / Skip, auto-skippable, with a 24h backstop that moves on without deciding for you), login-expired vs generic upload failure, "no MD files" gate, inter-phase gate (P2 produced no documents), and a **missing-podcast** skip that names which half failed — `no_audio_generated` vs `audio_generated_but_upload_failed` (the second still has the file on the research computer). Derived stems (`brief.md`, `consolidated.md`) are excluded from NotebookLM uploads via the `_DERIVED_STEMS` filter — never uploads consolidated.md.
- **Phase 4** — owned by FE (YouTube upload via Data API). BE no longer surfaces P4 errors; see FE for the alert matrix (`uploadYouTube 401/403/quotaExceeded` map to OAuth-scope / quota-cap actionable copy).
- **Phase 5** — owned by FE (Doc creation + email). BE no longer surfaces P5 errors; see FE for the alert matrix.
- **Cross-cutting** — Anthropic 429/529 narrate as retrying; other API errors surface as `pipeline_warning` on the current phase

### Alert intent catalog + non-blocking decisions (#955)

Alerts are authored through one seam — `emit_decision` (research.py ~14421) over an `ALERT_INTENTS` catalog (~14173) — so every actionable card carries a **recoverability class**, a `decision_id`, and (when auto-skippable) a deadline:

- **recoverable** → `[Retry][Skip]`; **hands_off** → Skip-only (Cloudflare/HV — a Retry would only re-hit the wall); **blocker** → must-act (e.g. a dead Anthropic key), never silently swallowed into a retry banner and it bypasses the dismiss-then-resurface ledger (FE #65); **infra** → environment/CUA-unavailable.
- **Non-blocking:** the P2 setup gates — HV (#1b), `pro_required` (#1a), `chat_mode` (#1c) — are send-before-decision and do **not** pause the round-robin; every alert **auto-resumes** on resolve, and the pause is released on every HV/skip/timeout path.
- **Auto-skip lifecycle** arm → fire → disarm; `HANDS_OFF_AUTO_SKIP_SEC=300` for hands-off walls (a longer unacted tier applies elsewhere). A **command-ack** is emitted at dispatcher intake so the FE re-enables the tapped button promptly.
- **Silent self-heals (no card):** a **Gemini "lost send"** is recovered silently — the agent adopts the existing sidebar chat (adopt-first) and, if needed, shows a one-**Retry** reconnect card (no "hard" retry); transient Anthropic errors retry silently before any card. A sticky Deep-Research tool on the P1 composer is cleared with **Backspace**, never a re-click (a re-click adds a *second* DR) (#952).
- **Gemini's own Redo, on a research that died (wave 10).** The post-Start window had never had a failure reader at all: the `[2D]` loop's re-draft branch is gated on `not start_clicked`, so it is dead from the moment Start research is pressed — and that is the moment this screen begins. A dead Gemini research went straight to salvage → card → park, with the control that would re-run it sitting unused in the failed turn. The new site calls the same `_gemini_redraft_plan` with `screen="research"` and adds nothing that decides anything. ⛔ **Redo opens a menu; it does not re-draft.** The re-draft lives on an overlay row the Redo click reveals (`data-test-id="regenerate-option"`), so treating the click as the outcome would burn the single attempt, report success, and leave a backdrop that swallows every later click — ours and the CUA ladder's. It runs **after** the salvage, deliberately, so a re-draft that replaces the turn cannot destroy the partial output we were about to keep; it is gated on something having already called the screen a failure, and it is mutually exclusive with the reload rescue by construction (`RELOAD_SAFE` is `{"ChatGPT", "Claude"}` — Gemini's SPA lands on the empty home, #897a). It still parks behind `[Retry] [Skip]` if the re-draft doesn't take.
- **Recovery backstops:** a permanently-dead worker's run is abandoned to `paused_backend_restart` (#64); a fleet respawn self-heals **per-worker** (not whole-fleet) (#966); the self-heal watchdog no longer fires a T1 push, and surfaces one honest Resume card (no misleading 2-min wait).

Default action on every alert is `[Retry] [Skip]`. Skip writes one unified command — `{"action": "skip_phase", "phase": N}` — and the dispatcher routes it by that phase number. *(This sentence used to name "the old `skip_phase` / `skip_phase` verbs" as the two things it replaced: the same verb, twice, so it said nothing. The per-phase verbs it meant are gone and nothing in the tree records what they were called, so the claim is dropped rather than guessed at.)* Phase-specific alerts may add `HV Resume` or `continue_anyway`. **Stop is NOT a per-phase action** — pause/stop/resume stay global in the app's chat input bar.

### Error matrix (normalized, Apr 19 late-late)

The per-alert action set was consolidated to reduce noise and remove affordances that invited broken states:

- **Default everywhere: Retry · Skip.** Every failure surface offers this pair unless it's specifically overridden below.
- **Workspace cap hit in Phase 2 → `End research` only** (`action=stop`). No point retrying when the user is out of workspace slots; other phases keep Retry · Skip.
- **Poll timeout in Phase 2 → auto-skip** (since 2026-04-30 `be8f7b3`). Removed the `Retry · Skip · Wait` alert; the BE saves whatever ≥200 chars it has and continues. Eliminates an indefinite human-decision wait.
- **Removed the "Proceed without CUA" option** (let users walk into broken-state pipelines with no recovery path). Poke morphed into the normalized Retry (which in turn does the hard tab close+reopen from the Apr 19 early `retry_agent` work).
- **Stuck-agent buttons relabeled** to match the normalized vocabulary: Poke → **Retry**, "Wait longer" → **Wait**, "Skip agent" → **Skip**.

## Stuck-state risk fixes (2026-04-30 `6545335` + `be8f7b3` + `549f079`)

Three classes of "pipeline silently wedged forever" caught and capped:

- **Manual brief 3h backstop** — `_BRIEF_WAIT_BACKSTOP_S = 3 * 3600`. If the user enabled "Provide my own brief" but never sends one within 3h of the chat-input prompt, `fail_phase` fires + emits `pipeline_stopped` with reason `manual_brief_wait_backstop_3h`. No more pipelines wedged on a vacant chat input.
- **Pending queue persist-failure surface** — `_persist_pending_queue` returns bool; if a Firestore write fails during BE shutdown handover, affected researches get `status=paused_backend_restart_failed` + `lastError` field with the actual exception string. FE renders this as a red error banner, not the green "queued" pill.
- **Dead-tab guard before soft retry** — in `poll_all_agents_round_robin`. Above the 2-hard-retry cap the loop checks whether the agent's tab is dead (closed / crashed); if dead, `fail_agent` fires + remove from pending. Prevents soft-retrying a corpse forever.
- **Browser crash auto-retry** — when 3 sites crash in the same window, `emit_browser_recovery_status` sends a passive banner to FE and bypasses the run_pipeline.finally retry guard. FE auto-clears the banner on resume (`auto_clear_on_resume=true` flag on AgentAlert). ⛔ **The banner's copy no longer promises a rebuild-and-resume, because measurably one does not happen.** It used to read *"auto-retrying from checkpoint… The pipeline will rebuild the browser session and resume"*; on a measured run Gemini's tab died at 17:21:00 and the phase reported COMPLETE at 17:21:06 with 2 of 3 agents — nothing was rebuilt, the agent was failed, and the run carried on. That promise is true only when the death takes the whole browser and an exception reaches `run_pipeline`, and one sentence was covering both cases. `browser_crash_copy` (pure, so it is testable) now reports only what was **observed** — who stopped responding, on whose page, how long it was quiet, how many times we re-checked — and **names no cause**: a stalled platform and a blind scraper are indistinguishable from here, and a dead tab looks the same whether the platform hung, Chrome ran out of memory or a profile lock was lost. It closes "Nothing on your side caused this; the run continued without it." ⚠ The quiet figure is a **floor** ("at least N minutes"), because an arbiter WORKING verdict rewinds the growth clock.
- **P2 timeout auto-skip** — drops the `await_agent_decision` block; if the agent has ≥200 chars of partial output, it's saved and the agent flips to skipped without human prompt.
- **Auto-retry kwarg forwarding** — `uid` / `research_id` / `run_id` are forwarded on the retry recursion (`_plan_pipeline_auto_retry` → `run_pipeline_captured`) so the Firestore listener stays attached on auto-retry. Without them `setup_firestore_run` is skipped and the FE's Stop button writes to a commands subcollection no one is listening to — the BE keeps running orphaned while the FE shows "stopped". `_submitted_by` rides the same call, because attempt 2 arms its OWN per-run log folder and a dropped writer would leave the attempt most worth sending attributable to nobody.

## CLI Mode

Run research directly from the terminal (no web app):

```bash
python research.py "Your research topic"
python research.py "Topic" --brief-file brief.txt     # Skip Phase 1
python research.py "Topic" --pdf paper.pdf             # Attach PDFs
python research.py --resume queue_name                 # Resume stopped run
```

**If the pipeline pauses** (most commonly Phase 0 `login_required`), the terminal prints a recovery menu:

```
[PAUSE] login_required — log in via the open browser, then:
  r) resume   s) skip phase   q) stop pipeline
>
```

After completing the login in the Chrome window the backend opened, type `r` + Enter to resume — Phase 0 re-verifies and the pipeline continues. `s` skips the current phase; `q` stops the run cleanly. Commands are accepted while stdin is a TTY; piped or headless runs see the menu but ignore typed input.

## Environment Variables

> **Recommended path**: set these in `.dg-supervisor.env` (auto-loaded by the supervisor at startup via `--env-file`; see [Step 2](#step-2-environment) above). The shell-env path below still works for manual debugging or legacy shell-rc setups — `resolve_api_key()` honors both.

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Anthropic API key for browser automation (CUA) + narrator's Haiku 4.5 cross-vendor fallback. Industry-standard name (matches the Anthropic SDK's auto-pickup). Legacy `CUA_API_KEY` is auto-migrated to this name on next BE startup. |
| `CUA_MODEL` | `claude-sonnet-4-6` | Claude model for CUA. Sonnet 4.6 is Anthropic's recommended CUA model (largest OSWorld jump in the 4.x lineup) and ~40% cheaper than Opus. Override via env for A/B tests. |
| `VISION_LIGHT_MODEL` | `claude-sonnet-5` | Claude model for the lightweight vision checks (login-wall detection, pro-tier detection). Decoupled from `CUA_MODEL` so they can evolve independently — bumped 4.6 → Sonnet 5 on 2026-07-22 while `CUA_MODEL` deliberately stayed on the Anthropic-recommended Computer-Use model. |
| `VISION_HEAVY_MODEL` | `claude-opus-5` | Claude model for the vision tier-2 high-stakes / retry-after-failure path (bumped 4.8 → Opus 5 on 2026-07-26). |
| `DG_VISION_TIER` | `off` | The single VisionRecipe / Track-B switch that arms the Vision **acting** tier. `off` = disabled; `shadow` = observe-and-log only (no acting); `act` (alias `tier2`) = Vision may act as the tier-2 fallback; `tier3` = deeper escalation. Leave `off` until validated (Vision is still CUA-primary). |
| `CUA_SCREEN_WIDTH` | `1280` | Browser viewport width |
| `CUA_SCREEN_HEIGHT` | `800` | Browser viewport height |
| `GEMINI_API_KEY` | (optional) | Gemini API key. Used by the narrator (Gemini Flash primary), summary helper, URL extractor, and other BE text tasks. (P4 thumbnail generation lives on the FE — `web/src/lib/album-art.ts` — and uses the FE-side env / per-user-pref Gemini key, not this BE one.) |
| `GEMINI_TEXT_MODEL` | `gemini-3.8-flash` | Gemini text model for summary, URL extraction, narrator primary. 2.5 Flash hard-deprecates 2026-06-17 on the generativelanguage API path — leave at default unless reproducing on the prior model. **Numbered on purpose:** a `gemini-flash-latest` alias exists and is GA, but the Flash line HAS a current numbered release, so pinning keeps a research run reproducible. |
| `GEMINI_NARRATE_MODEL` | `gemini-3.8-flash` | Gemini model for the vision-narrator (`narrate.py`) screenshot panel reader. Kept as its own env so the narrator can be tuned independently from text-only sites — but ⛔ **it moves with `GEMINI_TEXT_MODEL`, always**: `tests/test_gemini_thinking_config_rejected.py` rests on a 200-vs-400 differential between the two, so bumping one alone reds the suite. |
| `GEMINI_NARRATE_FALLBACK_MODEL` | `gemini-pro-latest` | Pro-class hedge against a Flash-specific outage in the vision narrator. ⛔ **An alias, unlike every other model constant here, and not by preference.** Measured against the live GA list 2026-09-17: the only Pro-class `generateContent` models are `gemini-2.5-pro` (deprecates 2026-10-16) and this alias — there is no numbered 3.x Pro at all. The old note said "holding on 2.5 Pro until 3.x Pro reaches GA"; the next Pro never landed and the runway expired. It costs reproducibility (Google can move an alias without warning) and that is accepted; pin a numbered GA Pro the day one appears. |
| `TITLE_MODEL` | `claude-haiku-4-5` | Claude model for research-title generation + API-key-validation tests. Same family as the narrator fallback. |
| `MAX_WAIT_DEEP` | `90` | Max minutes to wait per Phase 2 agent |
| `POLL_DEEP_RESEARCH` | `120` | Seconds between polling cycles (Phase 2 round-robin) |
| `MIN_AGENT_WAIT_MIN` | `5` | Minimum minutes from research-start before CUA completion check is allowed to fire |
| `BUG_REPORT_EMAIL` | (optional) | Where bug-report submissions land if FE bug-report uses the BE relay. FE has its own `BUG_REPORT_EMAIL` env on `/api/bug` — see FE README. |
| `DG_NARRATOR_USE_GEMINI` | `1` | Enable Gemini Flash as the narrator primary (Haiku 4.5 as cross-vendor fallback). Set `0` to force the Haiku path directly. (Renamed from `DG_NARRATOR_USE_HAIKU` 2026-05-28 when the primary swapped.) |
| `DG_NARRATOR_HAIKU_MODEL` | `claude-haiku-4-5` | Haiku model id for the narrator fallback. |
| `DG_VISION_NARRATE` | `0` | Re-enable the retired vision narrator (`narrate.py`, `PHASE_BUDGET=80/phase`). Set `1` if a coverage gap appears in DOM-derived narration. |
| `DG_ORPHAN_MAX_AGE_HOURS` | `4` | Cutoff age for `--retire`'s "manual one-off `--serve` runs" preservation. |

## File Structure

```
research-automate/
├── research.py                 # Pipeline + FastAPI server
├── prompts.py                  # CUA prompts for each phase
├── models.py                   # SINGLE SOURCE OF TRUTH for every model id + the P2 web-UI
│                               # model POLICY (P2_MODEL_POLICY: family + highest-offered, no
│                               # version literals) + UPSELL_VERBS. Bump a model here, not in research.py.
├── vision.py                   # Anthropic Sonnet vision client (tier-2 acting). Module surface:
│                               # default_client, is_vision_enabled, execute_action, act_loop,
│                               # shadow_observe_then_cua, observe_only,
│                               # reset_default_metrics.  (This line used to name `take_screenshot`
│                               # and `vision_action`; neither symbol exists anywhere in the repo.)
├── narrate.py           # Vision-tier panel narrator (PHASE_BUDGET=0 by default; retired 2026-04-30 — re-enable via DG_VISION_NARRATE=1)
├── selfheal.py                 # Phoenix self-heal SELECTOR engine (shadow-only; DG_SELFHEAL_ENABLED default OFF).
│                               # ⛔ Unrelated to research.py's own "Phoenix" (daemon restart/resume/checkpoint) —
│                               #    everything here is namespaced `selfheal` to kill the grep trap.
├── telemetry.py                # Content-free telemetry tier: every field is an int, a bool or an enum —
│                               # no free text at all, so there is nothing for a scrubber to miss.
├── logquiet.py                 # Repeat suppression for log lines whose information content is one bit
│                               # (three sites once ate 33.9% / 9.8% of a session log's bytes).
├── vision_test.py              # Fixture replay tool: --capture saves PNG+JSON, --fixtures replays + asserts action-class agreement + bbox containment
├── requirements.txt            # Python dependencies — runtime set mirrors pyproject.toml's [project]
│                               # dependencies exactly, plus the [dev] extra (pytest, pytest-asyncio, pinned ruff)
├── pyproject.toml              # Packaging: version, py-modules/packages ship-list, ruff pin + ruleset
├── ARCHITECTURE.md             # Backend architecture + Frontend ↔ Backend API contract.
│                               # ⛔ READ § Module boundaries BEFORE adding a subsystem:
│                               #    a new subsystem goes in a NEW module, not research.py.
├── .dg-supervisor.env          # Per-machine env config (gitignored; seeded from scripts/dg-supervisor.env.example on first --resurrect)
├── auth/                       # Pairing + credentials, shipped in the wheel as a package
│   ├── v2_flow.py              # The --pair handshake (initiate-pair → poll pending subdoc → token exchange)
│   ├── pairing.py              # Pair-state helpers
│   ├── credentials.py          # RefreshTokenCredentials (subclasses google-auth's Credentials)
│   └── keystore.py             # OS keystore slot rotation (DPAPI / Keychain / libsecret, chmod-0600 fallback)
├── agent/                      # The chat-runtime agent — a SEPARATE PyPI package (superresearch-agent)
│                               # with its own pyproject, requirements and pytest config. Root `pytest tests/`
│                               # never enters it; see agent/README.md.
├── tools/
│   ├── build_compiled.py       # Nuitka build — one wheel per OS × CPython minor (see § Python version)
│   ├── bump_version.py
│   └── check_release.py        # Run before publishing: refuses a release missing a platform's wheel, or whose source fingerprints differ or are missing
├── scripts/
│   ├── dg-supervisor.env.example  # Committed env-file template — install-time copied to .dg-supervisor.env if absent
│   ├── run_supervisor.cmd      # Manual-debug CMD helper (NOT wired into the Scheduled Task — supervisor invokes pythonw directly with --env-file)
│   └── vision_shadow_report.py # Per-hotspot agreement table from logs/vision_shadow.jsonl
├── tests/fixtures/vision/      # V1 Vision fixtures (PNG + JSON pairs); auto/ subdir is gitignored
├── .mutants/                   # MUTATION HARNESSES — one module per fix lane. Each holds the
│                               # anchored source edits that should break the tests guarding that
│                               # lane; a mutant the suite does NOT catch is a test that proves
│                               # nothing. This is how a fix is shown to be real here.
│   ├── _anchor_sweep.py        # Static: every anchor must match EXACTLY ONCE in its target. An
│   │                           # anchor that matches twice (or zero times) mutates the wrong line
│   │                           # and reports a kill. No tests run — seconds, so run it every time.
│   └── _apply_sweep.py         # Sequential: applies each mutant's edits IN ORDER to an in-memory
│                               # copy and ast.parse()s the result — catches the two blind spots a
│                               # resting-file sweep structurally cannot (an unparseable mutant
│                               # banking a free kill, and an anchor unique at rest but ambiguous
│                               # after the same mutant's earlier edit). Writes nothing.
└── queues/                     # Active/completed pipeline runs, beside the code (site-packages in an installed build)
    ├── .worker.{N}.lock        # One flat claim sentinel per worker — dual-spawn guard (see § Multi-Worker)
    └── {topic}_{timestamp}/    # meta.json, config.json, delivery.json, documents/, podcasts/

# tracks/ — REMOVED 2026-04-29. The directory tree is gone (its only
# artifacts, events.jsonl + per-platform scrape JSONs, were already
# unwritten when Firestore became the sole transport). Firestore
# `users/{uid}/researches/{rid}/pipeline_events/` is the sole event store.

# ⛔ PAIRING + RUNTIME STATE DOES NOT LIVE IN THE CODE DIR. Older builds kept
# these beside research.py — which is site-packages in a pipx build, so a
# `pipx upgrade` recreated the directory and ORPHANED the paired device.
# `_migrate_state_to_home()` moves any survivors on startup (best-effort,
# idempotent). `.dg-supervisor.env` is the deliberate exception: it stays in the
# code dir, because that is where --env-file looks for it by default.
~/.super-research/
├── research_config.json        # deviceId + pollSecret + pairedUid + workerCount (written by --pair; never commit)
├── pipe_config.json
├── run_analytics.json          # Historical phase durations (auto-updated; drives the ETA narration)
├── browser-profile[-N]/        # One persistent Chrome profile per worker — your platform logins
├── env-migrated-v1             # Sentinel for the one-shot CUA_API_KEY/GOOGLE_API_KEY rename
└── logs/                       # Machine-wide logs, per-run folders, and outgoing/ bundles for --send-logs.
                                # 30-day retention (LOCAL_LOG_MAX_AGE_DAYS), swept six-hourly on worker 1.
```

## Troubleshooting

**"No PipeToken found"** — Run `python research.py --pair` first.

**`ModuleNotFoundError: No module named 'patchright'`** — Run `pip install -r requirements.txt` again (patchright was added 2026-04-30; floor bumped to `patchright>=1.61` alongside `playwright>=1.61` on 2026-06-30). Then `python -m patchright install chrome`.

**`patchright` launches but Chrome doesn't open** — Patchright launches with `channel="chrome"` (real Chrome, not bundled Chromium). If real Chrome isn't installed on this machine, install it from google.com/chrome (Windows), `brew install --cask google-chrome` (macOS), or your distro's Chrome package (Linux).

**Backend shows "Offline" in the web app** — Make sure `python research.py --serve` is running. The heartbeat updates every **5 seconds**; the FE flips the dot red after **30 seconds** of silence (6 missed ticks).

**"Backend did not respond within 15s" / "didn't pick up the job"** — Only fires for immediate-claim submits (workers were free at submit time). Means the BE didn't ack within 15s — usually a transient Firestore RPC blip. Tap Retry. **Queued submits are exempt** as of 2026-05-22 (FE commit `992db14`) — they don't trigger this alarm even if claim takes minutes, which it legitimately can when all workers are busy with cross-account runs.

**Two researches running at once on one PC** — Expected under `workerCount > 1`. See § Multi-Worker above. Not a bug.

**Browser sessions expired** — The lighter path is now `python research.py --login`: it runs a **per-profile Y/N walk** (same as pair Stage 5) fronted by a **read-only pre-probe** that leaves any still-valid session **intact** — it only re-opens your real Chrome for the profiles you say Y to, so an already-signed-in profile is never blown away. Sign into the platforms + clear any Google/Cloudflare human-check in that window. It does **not** run the patchright login/Pro-tier verify pass (`--login` never verifies). Re-running `python research.py --pair` also logs you in again.

**NotebookLM login expired mid-run** — Surfaces as a Phase 3 alert with `login_expired` detail (distinct from generic upload failure). Re-run `--pair` to refresh that session; hit `[Skip]` on the alert if you want to move past Phase 3 and still get Phase 5 report/email.

**Anthropic 429 / 529 (rate-limit or overload)** — Retries automatically with narration in the current phase dropdown; usually self-resolves within one or two attempts.

**Anthropic API key invalid (401)** — *(chain corrected: this entry described the pre-2026-05-28 direction, Haiku-primary → Gemini-fallback, and quoted a log line that no longer exists.)* **Narration is unaffected** as long as a Gemini key is set, because Gemini Flash is the narrator **primary** — Haiku is the cross-vendor hedge, so a dead Anthropic key costs you the hedge, not the narration. What it DOES cost: CUA tier-3 stops working (the pipeline relies on Playwright tier-1 / Vision tier-2 only), the vision tiers go with it, and Haiku-backed title generation (`TITLE_MODEL`) fails. The log line to look for is the opposite downgrade — `[narrator] Gemini <model> refused the call — HTTP … — narration is running on claude-haiku-4-5 until this is fixed`, emitted **once** per narrator loop, not per tick. Check your Anthropic billing/keys page.

**Anthropic workspace usage limit hit (CUA 400)** — Same fallback semantics as 401: narrator routes to Flash; CUA tier-3 is unavailable until the limit window resets (typically 24h). Pipeline keeps running on Playwright + Vision; specific platform actions that require CUA (e.g. some HV captcha clicks) may need manual help via the FE alerts.

**Phase 4 audio failed but Phase 5 still matters** — Hit `[Skip]` on the FE Phase 4 alert; FE-P4's fast-path skip emits `phase_skipped:4` and chains directly into FE-P5 (Doc + email) without a YouTube URL.

**FE shows `paused_backend_restart_failed` red banner** — Backend tried to persist the in-flight queue on shutdown but the Firestore write failed. The `lastError` field on the research doc has the actual exception. Restart `--serve`; affected runs are kept on disk in `queues/` and can be resumed via the FE checkpoint banner once BE is back online.

**CLI mode pause hangs (no web app)** — `python research.py "topic"` running standalone (without `--serve`) cannot use the app's Skip/Retry buttons. When Phase 0 emits `login_required` (or any other pause), the terminal prints a recovery menu:

```
[PAUSE] login_required — log in via the open browser, then:
  r) resume   s) skip phase   q) stop pipeline
```

Complete the login in the open Chrome window, then type `r` + Enter to resume. `s` skips the current phase; `q` stops cleanly. Useful for headless rigs and onboarding before the web app is available. The menu only accepts input when stdin is a TTY — piped/Task-Scheduler runs print the menu but ignore typed input.

---

Built for Distributed Global.
