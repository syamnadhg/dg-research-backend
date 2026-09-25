#!/usr/bin/env python3
"""sr.py — the Super Research skill's thin client to the host bridge.

A chat runtime (Hermes / OpenClaw) runs this via `exec` and relays the output to
the user. It is intentionally STANDALONE and dependency-free (stdlib urllib
only) so it can live in the runtime's skills dir without the facade installed.

It only ever talks to the loopback bridge (127.0.0.1:<port>) that `agent serve`
runs; it never touches Firestore, tokens, or the network directly. Every
account action is the bridge's responsibility (single-owner session).

Commands (mirror the chat slash actions). A run is named by its TITLE (a word
or two from the topic) or run-id; omit it to mean the most recent / active run:
  login              start a remote sign-in → prints a link to relay
  login-done         check once whether the sign-in was approved (alias: login-wait)
  status-account     is the bridge up + signed in?
  devices            list this account’s devices, each with an online flag
  device-use <name>  choose the device runs go to (name or id)
  device-add <code>  pair a new device by the code on its screen
  device-remove <name>  unlink a device (owner: new access code issued; sharer leaves)
  research <topic>   start a run (--device <id> to override the selected device)
  status [run]       a run's progress + links + any blocker (no run = most recent)
  podcast [run]      download a run's audio → a local file to send as native audio
  updates            active runs + their links + any that need you (streaming cron)
  stop [run]         gracefully stop a run, keeping the results so far + the chat
  retry [run]        resume a run that's waiting on a decision / hit an error
  skip [phases…]     skip the run's current blocker (no phases) or named phases
                       (--run <run> to target one; else the latest active run)
  arm-stream         arm this chat's streaming watchdog (writes the job itself;
                       older runtimes get a printed cron script to arm by hand)
  version            show the Super Research skill version
  update             update the Super Research skill (this chat — scripts + bridge)
  logout             clear the account session

Add --json to print the raw bridge response INSTEAD of the friendly lines.
⛔ --json REPLACES the rendered text, so a reply whose lines carry a warning
loses the warning: `--json device-remove` prints the new access code with none of
the three sentences that say the old one is dead, that this one claims the
machine, and to keep it like a password. Callers that render for a person must
not use it.
⛔ THE LIVE-UPDATES CRON IS `sr_attention_poll.py`, NOT THIS. It reads the
bridge's /updates directly and imports nothing from here; the claim that the
cron used `sr.py --json updates` was false and only two tests ever called it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

try:
    import fcntl  # POSIX advisory file lock. The Hermes host is always POSIX;
except ImportError:  # None elsewhere (e.g. a Windows test import) → lock-free write.
    fcntl = None

# The version of the agent package THIS script copy shipped with. The runtime
# executes its own installed COPY of this file (HERMES_HOME/scripts), which a
# `pip install -U` on the host does NOT refresh — only `connect` / “update”
# redeploys it. cmd_version compares this against the live bridge's version so a
# stale chat-side copy names itself instead of misbehaving
# silently (live 2026-07-02: a stale copy predating the podcast MEDIA: fix
# kept sending bare audio paths). Bumped together with pyproject.toml —
# guarded by tests/test_sr_skip_agents.py::test_skill_build_matches_package_version.
_SKILL_BUILD = "0.1.33"

_TIMEOUT = 30
# By-title run resolution scans the newest N runs (status / podcast / list / the
# resume verbs). 20 was too shallow — a run a few weeks back (named, not active)
# fell outside the window, so `podcast "Rocky Port…"` silently found nothing and
# the agent improvised. 100 covers a deep history; it's a plain Firestore list
# (no per-phase minting — that's only the via=agent `updates` path, left at 20).
# Mirrors the bridge's /updates limit cap (bridge.py `_updates`).
_LOOKUP_LIMIT = 100

# The human setup page (per-OS install + the pairing step that ends in the access
# code). A BARE URL — it auto-links on every channel, and Markdown would hard-code
# a rich-text channel assumption. Kept distinct from the install.ps1/.sh SCRIPT
# URLs, which never appear in chat.
_INSTALL_PAGE_URL = "https://superresearch.io/install"

# ⭐⭐ THE ONE ADD-A-COMPUTER LINE, AND THE LINK IS INSIDE IT (owner, 2026-09-24).
# Every chat surface that tells a person how to add a computer renders THIS
# constant — the no-computer screen, the tail of a populated device list, the
# one-line confirmation after sign-in, and the router's answer to "install
# Super Research" / "where do I get an access code". The watcher and the terminal
# cannot import it and say the same words in their own files.
#
# ⛔⛔ MEASURED, NOT GUESSED. The install link used to be its own paragraph at the
# END of the screen, opening "Don't have your own Research Computer yet?", with a
# second code sentence under it: "It gives you an 8-char access code". In the
# Hermes history the link survived 0 of 3 relays of the `devices` screen
# (2026-09-19 · 09-21 · 09-24). A condensing model drops a trailing paragraph and
# a conditional aside, keeps ONE sentence about connecting a computer, and
# resolves a pronoun on its own: "It" (the page) became "an 8-character access
# code from the Super Research app", which is false for anybody without a
# computer. So the link now travels INSIDE the one sentence a relay always keeps,
# it is the only sentence on the screen that names the code, and it says where
# the code really comes from: the computer, at the end of that setup.
#
# ⛔ "OR ONE A COMPUTER'S OWNER GAVE YOU" STAYS IN THE SAME SENTENCE. An access
# code connects ANY computer running Super Research, so this route was never
# "your own" only (owner, 2026-09-20) — somebody else's private machine joins the
# same way, with the code its owner hands over.
#
# ⛔ NOT `--pair` ANYWHERE A NEW PERSON READS. The page carries the commands, per
# OS, and stays current when they change; a chat message cannot. `--pair` remains
# the right instruction only for a machine that is ALREADY set up and needs a
# fresh code (the device-add errors, unlink) — those sites keep it deliberately.
_ADD_A_COMPUTER = (f"Add a computer: set one up at {_INSTALL_PAGE_URL}, then send "
                   "me the 8-character access code the computer shows (or one a "
                   "computer's owner gave you).")

# ⭐ A LOST OR SHARED CODE HAS ITS OWN ANSWER (owner, 2026-09-24). "I lost my access
# code", "I need a new one", "what's my computer's code" come from somebody whose
# computer ALREADY EXISTS, so `_ADD_A_COMPUTER` — set one up — is the wrong answer
# (the page's setup ends in the pairing step, which mints a NEW computer and drops
# everybody it was shared with). They reached the catch-all, and the assistant
# improvised where a code lives. Three true places, checked against the web app:
# the owner's tap-to-reveal on the computer's tile in Account (PIN-gated), Reset in
# Settings → Manage devices (the new code is emailed), and — mid-setup — the screen
# of the computer being set up.
_LOST_CODE_REPLY = ("If the computer's already on your account, open Account in the "
                    "web app and reveal the access code on that computer's tile "
                    "(you'll enter your PIN). For a new one, use Reset in Settings → "
                    "Manage devices and we'll email it to you. If you were still "
                    "setting it up, the code is on that computer's screen.")

# ⛔⛔ THE SAME CLAIM ON EVERY SCREEN THAT MAKES IT. The consent question was
# corrected in 7.9-2 — the owner sees the NAME, and the email only when no name is
# set — and the browse list's own trailer went on saying "your name and email
# address" for two waves, which is the phrasing a sibling test forbids by name.
# One string, so the invitation and the confirmation cannot say different things
# about what asking costs.
# ⛔⛔ AND IT OFFERS THE ID, BECAUSE THE ROWS ABOVE IT COLLIDE. Every unnamed
# machine reads as the identical string "Research computer", so "tell me which one"
# alone is a question the reader may not be able to answer — and the resolver
# refuses an ambiguous name rather than guessing.
_PUBLIC_ASK_INVITE = ("Tell me which one to ask for. Once the request is accepted "
                      "you can use that computer. They see your name.")

# ⛔ ONE EXPLANATION OF AN EMPTY PUBLIC LIST. The two screens ask different
# questions — "are there any?" and "I have none, is there another way?" — so the
# lead differs and the word "either" only belongs on the second. The REASON is
# identical and is shared, because that is the half that can drift into two
# stories about how a computer gets onto that list.
_PUBLIC_NONE_WHY = "A computer shows up there only when its owner switches that on."

# ⛔⛔ TRUNCATION IS ABOUT THE SCAN, NOT ABOUT THE LIST, and the empty branch is
# where it matters most: zero rows plus a filled scan means everything found was
# filtered out, over which a flat "nobody is offering" is the one reading that is
# definitely wrong.
_PUBLIC_TRUNCATED_SOME = ("(There are more public computers than one look can "
                          "scan, so some may be missing.)")
_PUBLIC_TRUNCATED_NONE = ("(There were more machines than one look can scan, so "
                          "this may not be the whole story.)")

# ⛔ SHORTER THAN THE BROWSE COMMAND'S OWN 40s. This look is a SECOND fetch on a
# screen that is already answering something else — a run that could not start, a
# name that would not resolve — so it must not be able to hold that answer open for
# the whole client budget.
# ⛔⛔ AND IT IS DELIBERATELY SHORTER THAN THE BRIDGE'S OWN WORST CASE, NOT LONGER.
# The bridge allows the web app 15s and then RE-MINTS ITS TOKEN AND TRIES AGAIN on
# a 401, so its true ceiling for this route is about thirty. Waiting that out would
# make the empty state the slowest screen in the client; giving up first and saying
# so is the trade, and the sentence below is what a reader gets for it.
_PUBLIC_LOOK_TIMEOUT = 20

# ⭐⭐ THE NOUN, ONCE, FOR BOTH SCREENS. The browse list has always been headed
# "Public computers (N):"; the empty state rendered the IDENTICAL rows under "Or
# ask to use somebody else’s — …" and never printed the noun at all. A person
# arriving with no computer therefore met the concept as the tail of a sentence
# rather than as a section, and a relay — which restructures what the client
# leaves implicit and preserves what it states — folded it into the option above
# it and the section vanished from the chat (owner, 2026-09-20).
#
# ⛔ SO THE HEAD IS A CONSTANT AND BOTH SCREENS TAKE IT FROM HERE. Two screens
# rendering one list under two different names is the drift this file’s comments
# keep being written about; the count belongs to the browse screen alone, because
# the empty state is naming an option rather than reporting a scan.
_PUBLIC_HEAD = "Public computers"

# ⛔ FALSE ONLY UNDER --json, where `_emit` prints the payload and drops the lines.
_RENDERING_LINES = True


def _public_offer_lines() -> list[str]:
    """The "or ask to use somebody else's" half of the empty state, with the ones
    on offer LISTED.

    ⛔⛔ THE OFFER SURVIVES A FAILED LOOK. Dropping the paragraph when the fetch
    fails would put this screen back where it was before this wave — one way out,
    and it needs hardware the reader may not have. The option is true whether or
    not the list could be fetched, so it is stated either way and the verb that
    retries it is handed over.
    """
    if not _RENDERING_LINES:
        return []
    code, body = _get("/devices/public", timeout=_PUBLIC_LOOK_TIMEOUT)
    if code != 200 or not isinstance(body, dict):
        # ⛔ A REFUSAL WITH A WAIT IS NOT THE SAME AS A FAILED LOOK. Browse is rate
        # limited and the reply carries the number of minutes; telling somebody to
        # ask again immediately spends another look on the same refusal.
        said = _list_refusal_line("looked for public computers",
                                  str(body.get("error", "")) if isinstance(body, dict) else "",
                                  body.get("retryAfterMs") if isinstance(body, dict) else None)
        if isinstance(body, dict) and body.get("error") == "rate_limited":
            return [f"{_PUBLIC_HEAD} — ask to use somebody else’s. "
                    f"{said}"]
        return [f"{_PUBLIC_HEAD} — ask to use somebody else’s. Say "
                "“show me public computers” and I’ll look again."]
    rows = [d for d in (body.get("devices") or []) if isinstance(d, dict)]
    if not rows:
        # ⛔⛔ THE THIRD THING IS STILL SAID WHEN THERE ARE NONE. "Nobody is
        # offering one" on its own answers a question this reader did not ask and
        # silently drops the option — they are left with the access code again, which
        # is the dead end this whole block exists to remove. The option is named,
        # then the truth about today.
        # ⛔ AND THE SHARED SENTENCE KEEPS ITS OWN LINE. Splicing it after an
        # em-dash printed "— A computer shows up there…" with a capital A
        # mid-sentence; it is written as a sentence because the browse screen uses
        # it as one.
        lines = [f"{_PUBLIC_HEAD} — ask to use somebody else’s. Nobody is "
                 "offering one publicly right now.",
                 _PUBLIC_NONE_WHY]
        if body.get("truncated"):
            lines.append(_PUBLIC_TRUNCATED_NONE)
        return lines
    # ⛔⛔ "ON OFFER" IS FALSE WHEN EVERY ROW IS FULL. `full` means the ask route
    # answers `share_cap_reached` with certainty, so a list of nothing but full
    # machines is an invitation to spend one of five hourly asks on a guaranteed
    # no — the exact defect 7.9-3 removed from the ask verb, reintroduced by the
    # screen that offers it.
    if all(d.get("full") for d in rows):
        lines = [f"{_PUBLIC_HEAD} — ask to use somebody else’s, but every "
                 "computer on offer is already shared with as many people as it "
                 "can hold:"]
    else:
        lines = [f"{_PUBLIC_HEAD} — ask to use somebody else’s; these are on "
                 "offer right now:"]
    lines += _public_rows_block(rows)
    if body.get("truncated"):
        lines.append(_PUBLIC_TRUNCATED_SOME)
    lines.append("")
    lines.append(_PUBLIC_ASK_INVITE)
    return lines


# ⭐⭐ THE RELAY RULE FOR THE NO-COMPUTER SCREEN, CARRIED IN BAND (owner,
# 2026-09-21). Measured, not guessed: asked "Add device to my Super Research", the
# chat ran `status-account` AND `devices`, both printed this screen exactly as
# designed THEN — state of play, "Add a computer:", the public computers as a named
# section with its list, the walkthrough last (since 2026-09-24 the link rides in
# the add line instead; see `_ADD_A_COMPUTER`) — and the reply the person got
# dropped the section heading, demoted the list to an "Alternatively…" aside,
# led with `superresearch --pair` in a fenced block, and lost the install link.
# The client was right; the relay was not.
#
# ⛔⛔ AND THAT FENCED BLOCK WAS NOT IMPROVISED — SKILL.md PRESCRIBED IT. Its
# "wants to add a computer but hasn't given a code" recipe said to ask for the code
# and then showed exactly that block, and its formatting rule said to fence every
# setup command. An in-band rule fighting a written recipe is a coin toss, so the
# recipe, the routing row that sent a no-code request to `device-add`, and the
# fence rule were all rewritten in the same change (an earlier comment here called
# the block "of its own invention"; a review of SKILL.md showed it was not).
#
# ⛔ IN BAND, BECAUSE PROSE ALREADY FAILED. SKILL.md says "relay verbatim" a
# dozen times and it was not enough for the send-logs plan either; the two relay
# rules in this skill that have held are both attached to the bytes they govern
# (`_AGENT_ONLY_MARKER` blocks and the `MEDIA:` line). This screen had no anchor.
#
# ⭐⭐ SHORT, AND IT CARRIES THE URL ITSELF (owner, 2026-09-24). The rule that
# stood here was a long ordering clause — "…then the install link, then any line
# after it…" — and it was in the tool output of the 2026-09-24 relay that dropped
# the link anyway: it could name the link but never put one back, and it never
# said where the code comes from, so the model invented "from the Super Research
# app". Now the URL is written into the rule literally, the code's true origin is
# stated, and the only ordering left is the one the screen already prints.
# ⛔ "AS PRINTED" STILL COVERS THE LINES AROUND THE SCREEN. The sign-in paths
# print the sign-in line and a held-topic promise before it; both sit above the
# marker, so both are part of "the screen above". (`status-account` no longer
# prints the screen at all — a login answer is about login only, owner
# 2026-09-25.)
_EMPTY_STATE_RELAY = (
    "⛔ Relay the screen above as ONE message, as printed. Keep "
    f"{_INSTALL_PAGE_URL} inside the “Add a computer” sentence and keep the "
    f"“{_PUBLIC_HEAD}” section with every row. The access code comes from the "
    "person's computer at the end of that setup — never say it comes from the "
    "app, and add no commands (no `superresearch --pair`).")


def _with_empty_state_relay(lines: "list[str]") -> "list[str]":
    """Close a message that ENDS with the no-computer screen with its relay rule.

    ⛔⛔ ONLY AT A TERMINAL EMIT SITE, NEVER INSIDE THE SHARED RENDERER.
    Everything below `_AGENT_ONLY_MARKER` is hidden from the person, so the block
    has to be the LAST thing in the message. Two of the renderer's callers return
    it as a fragment that other code extends — `_pick_device_lines` (send-logs
    then adds its own sentence about the agent's log) and the sign-in note — and
    a directive baked into the renderer would silently swallow whatever they
    append. So each message that ENDS here attaches it itself: `devices` and
    `research` on an empty account, `login-done` when the
    sign-in note says there is nowhere to run, every device command whose name
    lookup found no computer at all (via `_resolve_device_arg`), and `updates`
    when the sign-in note it took says there is nowhere to run (there the rule
    joins any re-arm directive under the ONE marker, as its last line).

    ⚠ KNOWN UNCOVERED, DELIBERATELY: `send-logs` with no computer renders the
    screen through `_pick_device_lines` and then appends its own agent-log offer,
    and `research`'s which-computer fallback reaches it only when a re-fetched
    device list comes back empty. Neither is a whole-message tail today. Both
    still carry the link where a relay keeps it — inside the add line.

    ⛔ NOT ON THE WATCHDOG'S LINE OR THE TERMINAL. The watchdog runs `no_agent`,
    so nothing relays it; the terminal prints straight to a person.
    """
    return [*lines, *_agent_directive_block([_EMPTY_STATE_RELAY])]


def _no_device_lines(lead: str | None = None) -> list[str]:
    """THE empty state. Every screen that tells somebody this account has no
    research computer renders it through here.

    ⛔⛔ TEN SENTENCES USED TO SAY THIS AND THEY ALL SAID SOMETHING DIFFERENT —
    the list command, the status line, a name that would not resolve, a run that
    could not be routed, the sign-in announce, the picker's own fallback, the
    watcher, and the terminal. Every one of them offered exactly ONE way out:
    paste an access code. Somebody with no machine of their own, and no way to get
    one, was told to go and get one.

    ⭐ THREE THINGS, IN THIS ORDER, EVERY TIME. There is no computer on this
    account · “Add a computer:” — the install page, then the access code that
    computer shows (or one its owner gave you), in ONE sentence · or you can ask to
    use somebody else's — and the ones on offer are LISTED, because "ask for a
    public one" with no list is advice rather than a next step.

    ⛔ AND NOTHING AFTER THE PUBLIC SECTION (owner, 2026-09-24). The install link
    used to close the screen as a paragraph of its own; that is the part a
    condensing relay dropped every time it was measured. It lives inside the add
    line now (see `_ADD_A_COMPUTER`), so the screen ends on the public section and
    the caller's relay rule, if any, follows it.

    ⛔ `lead` is for the callers that arrive with an object already in hand (a
    topic that has nowhere to run). It is NOT a second phrasing of the three
    things — it names what was being attempted, and the three things follow it
    unchanged, as a block of their own (a blank line after the lead, owner
    2026-09-25).
    """
    lines = [lead, ""] if lead else []
    lines.append("No research computer on this account yet.")
    lines.append("")
    # ⛔⛔ NOT NUMBERED, AND NOT COUNTED — THERE IS NO HONEST NUMBER TO GIVE
    # (owner, 2026-09-20). A first version of this headed the block "Two ways in:"
    # and numbered the options 1 and 2. Both are false: an access code connects
    # ANY computer running Super Research, so "add a computer" already covers a
    # machine of your own AND somebody else's private machine whose owner hands
    # you the code — which is a third way in that the count silently denied.
    # A wrong number is worse than no number: it tells the reader to stop looking.
    #
    # ⭐ WHAT THE SECTIONS NEEDED WAS NAMES, NOT ORDINALS. The defect this block
    # was rewritten for was that the public half had no NOUN — it read as the tail
    # of a sentence, so a relay folded it into the option above it and the list
    # left the message. The names fix that; the numbers were never load-bearing.
    lines.append(_ADD_A_COMPUTER)
    pub = _public_offer_lines()
    if pub:
        lines.append("")
        lines += pub
    return lines


def _base() -> str:
    # Read the port lazily so the env can be set per invocation. Always loopback;
    # the env only chooses the port (validated — never a host).
    #
    # ⛔⛔ EMPTY IS UNSET, NOT BAD, AND THIS COPY USED TO DISAGREE — LOUDLY. A
    # variable that is SET AND EMPTY (a shape a shell exports readily) came back
    # as "" rather than the default, `int("")` raised, and this printed
    # "(ignoring bad SUPER_AGENT_BRIDGE_PORT ''; using 9876)" TO STDERR ON EVERY
    # SINGLE INVOCATION — while the bridge, and the other three copies of this
    # rule, silently treated the same value as unset. Found by executing the two
    # against each other rather than by reading them.
    raw = (os.environ.get("SUPER_AGENT_BRIDGE_PORT") or "").strip()
    port = 9876
    if raw:
        try:
            val = int(raw)
            if 1 <= val <= 65535:
                port = val
            else:
                raise ValueError
        except ValueError:
            print(f"(ignoring bad SUPER_AGENT_BRIDGE_PORT {raw!r}; using 9876)",
                  file=sys.stderr)
    return f"http://127.0.0.1:{port}"


def _request(method: str, path: str, body: dict | None = None,
             timeout: float | None = None) -> tuple[int, dict]:
    url = _base() + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout or _TIMEOUT) as resp:
            raw = resp.read()
            status = resp.status
            try:
                return status, (json.loads(raw) if raw else {})
            except ValueError:
                # A non-JSON 200 (proxy/HTML error page, truncated body) would
                # otherwise escape as a raw traceback to the chat runtime.
                return status, {"error": f"HTTP {status} (unexpected non-JSON reply from the bridge)"}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, (json.loads(raw) if raw else {})
        except ValueError:
            return e.code, {"error": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return 0, {"error": f"bridge unreachable ({e.reason}) — the Super Research bridge "
                            "isn't running on this machine yet. Set it up with `pipx run "
                            "--no-cache superresearch-agent connect` (it starts the bridge + keeps it "
                            "on login), then sign in."}
    except OSError as e:
        # HTTPError/URLError are OSError subclasses handled above, so this last
        # clause absorbs read timeouts (socket.timeout is TimeoutError) and other
        # low-level socket/OS errors into the same friendly line instead of a
        # raw traceback.
        return 0, {"error": f"bridge unreachable ({e}) — the Super Research bridge "
                            "isn't running on this machine yet. Set it up with `pipx run "
                            "--no-cache superresearch-agent connect` (it starts the bridge + keeps it "
                            "on login), then sign in."}


def _get(path: str, timeout: float | None = None) -> tuple[int, dict]:
    return _request("GET", path, timeout=timeout)


def _post(path: str, body: dict | None = None,
          timeout: float | None = None) -> tuple[int, dict]:
    """⛔ `timeout` IS PER CALL because one route needs longer than the rest.
    `/device/remove` can take the bridge up to 35s (the web route declares a 30s
    budget and uses it), and a client that gave up first would report a bridge
    that is not running AND lose the only copy of the machine's new access code."""
    return _request("POST", path, body if body is not None else {}, timeout=timeout)


def _emit(payload: dict, as_json: bool, lines: list[str], code: int = 0) -> int:
    """Print either the raw JSON (cron) or the friendly lines (chat relay).

    Returns the process exit code so the streaming cron can tell success (0)
    from a bridge/session failure (non-zero)."""
    if as_json:
        # ⛔⛔ THE WARNING RIDES ALONG IN JSON TOO. `--json` prints the payload
        # INSTEAD of the rendered lines, so `--json device-remove` emitted the
        # rotated access code with none of the three sentences that say the old one
        # is dead, that whoever holds this one can claim the machine, and to keep
        # it like a password. A machine-readable caller is still read by somebody.
        # Cross-verify found it; nothing in either new test file drove `--json`.
        # ⛔ `pairCode` AND `pairCodeWarning` ARE WIRE NAMES A CHAT RUNTIME READS
        # — only the sentence inside moves to the web app's "access code".
        if isinstance(payload, dict) and payload.get("pairCode"):
            payload = {**payload, "pairCodeWarning":
                       "This is the machine's new access code. Whoever holds it can "
                       "claim the computer as its owner. The previous code no "
                       "longer works and this is the only copy."}
        print(json.dumps(payload))
    else:
        print("\n".join(lines))
    return code


def _fail_code(http_code: int) -> int:
    # 2 = bridge unreachable (http_code 0); 1 = any other non-200.
    return 2 if http_code == 0 else 1


# A do-not-relay marker for handing the chat AI a TOOL directive (e.g. the
# streaming cronjob) without it leaking into the chat. SKILL.md defines the
# contract: relay everything ABOVE this line verbatim; act on everything BELOW it
# SILENTLY (call the tool, never quote it, never announce it) — which is what
# fixes both the cluttered "Started" message and the duplicate "signing you in"
# message (the AI narrated the arming twice because the directive was mixed into
# the user text). Nothing runtime-specific is baked in — a runtime with no such
# tool just ignores the block, so it works AGAINST no runtime.
_AGENT_ONLY_MARKER = "── for the assistant · do NOT relay to the user ──"


def _agent_directive_block(directive_lines: list[str]) -> list[str]:
    """Wrap assistant-only instruction lines under the do-not-relay marker."""
    return ["", _AGENT_ONLY_MARKER, *directive_lines]


# ⭐ THE WEB APP'S OWN NAMES for the two documents it writes at delivery
# (doc-kinds.ts FULL_LABEL). "Super Research" is the product name the synthesised
# document literally carries in the delivered Doc, so shortening it here would put
# a second spelling of one document in front of the same person.
_SR_LINK_LABELS = {
    "brief": "Brief", "chatgpt": "ChatGPT report", "gemini": "Gemini report",
    "claude": "Claude report", "synthesis": "Super Research",
    "consolidated": "Consolidated", "summary": "Summary", "podcast": "Podcast",
}

# ⛔⛔ ONE COMBINED DOCUMENT, NEVER BOTH — the same rule the bridge and the
# delivered Google Doc apply. The web synthesises `synthesis` from the material
# the machine stacked into `consolidated`, so listing both prints the same
# document twice under two names; the web app hides the stack whenever a
# synthesis exists (doc-kinds.ts `visibleDocuments`). `consolidated` is never
# minted any more, but an older re-delivered run still carries its share — so it
# stays as the FALLBACK rather than being dropped, or such a run would show no
# combined document at all.
_SR_COMBINED = ("synthesis", "consolidated")


def _fmt_sr_links(sr_links: dict) -> list[str]:
    """The permanent Super Research share links (the ones in the delivered doc —
    they never expire or get revoked). These are what to hand out when the user
    asks for "the podcast link" / a doc link."""
    if not sr_links:
        return []
    out = ["  Permanent links (never expire — safe to share):"]
    # ⛔ PODCAST STAYS FIRST — this block answers "the podcast link" more often
    # than anything else. The documents then follow the delivered Doc's own order.
    combined_done = False
    for key in ("podcast", "brief", "chatgpt", "gemini", "claude",
                "synthesis", "consolidated", "summary"):
        if key in _SR_COMBINED:
            if combined_done:
                continue
            if sr_links.get(key):
                combined_done = True
        url = sr_links.get(key)
        if url:
            # Channel-neutral (label + bare URL): the raw URL auto-links on every
            # channel (Telegram/WhatsApp/SMS/…), and the runtime is free to render
            # it as a clickable label where it can. We do NOT emit Markdown here —
            # that would hard-code a rich-text channel assumption into the skill.
            out.append(f"  🔒 {_SR_LINK_LABELS.get(key, key)}: {url}")
    return out


def _fmt_phase_updates(phase_updates: list) -> list[str]:
    """Per-phase links for a status snapshot — one block per DONE phase. Carries the
    SR permanent links (🔒: Brief + the agent reports + the Super Research and
    Summary documents + the Podcast) AND the real
    platform links (🔗: NotebookLM + YouTube + the Google Doc). Mirrors what the
    streaming watchdog posts so a manual `status` shows the SAME links. On-demand
    path: lists the links available SO FAR while a run is mid-flight (the proactive
    watchdog holds the full set until the end)."""
    out: list[str] = []
    for pu in phase_updates or []:
        p, name, st = pu.get("phase"), pu.get("name", "Phase"), pu.get("status")
        if st == "skipped":
            out.append(f"  ⏭ Phase {p} ({name}) skipped")
            continue
        out.append(f"  {'🎉' if pu.get('final') else '✓'} Phase {p} ({name}) complete")
        for lk in pu.get("links", []) or []:
            url = lk.get("url")
            if not url:
                continue
            glyph = "🔒" if lk.get("permanent") else "🔗"
            # Channel-neutral label + bare URL (no Markdown — see _fmt_sr_links).
            out.append(f"     {glyph} {lk.get('label') or 'link'}: {url}")
    return out


# Phase numbers match the web app's pipeline (P1 Brief · P2 Deep Research ·
# P3 Podcast · P4 Video · P5 Report/Email) so the agent can answer "is P4/P5
# skipped?" directly from this line.
def _fmt_pipeline_config(cfg: dict | None) -> list[str]:
    """One compact line of which phases are ON / OFF for a run, so the agent can
    answer "is video / podcast / email skipped?" from a status check. Reads the
    run doc's live ``pipelineConfig`` (the FE toggle + /sr skip both write here);
    tolerates the agent-start ``skipPhases`` alias of ``skippedPhases``. Returns
    [] when there's no config to report (a legacy doc) rather than inventing one."""
    if not isinstance(cfg, dict) or not cfg:
        return []
    skipped: set[int] = set()
    for key in ("skippedPhases", "skipPhases"):
        v = cfg.get(key)
        if isinstance(v, list):
            skipped.update(p for p in v if isinstance(p, int) and not isinstance(p, bool))
    raw_agents = cfg.get("agents") if isinstance(cfg.get("agents"), dict) else {}
    on_agents = [name for name, key in (("ChatGPT", "chatgpt"), ("Gemini", "gemini"), ("Claude", "claude"))
                 if raw_agents.get(key, True)]

    def _s(on: bool) -> str:
        return "on" if on else "OFF"

    research_on = (2 not in skipped) and bool(on_agents)
    research = f"P2 Research {_s(research_on)}"
    if research_on:
        research += f" ({', '.join(on_agents)})"
    return [
        f"  ⚙ Phases: P1 Brief {_s(1 not in skipped)} · {research} · "
        f"P3 Podcast {_s(3 not in skipped)} · "
        f"P4 Video {_s(cfg.get('videoEnabled', True) is not False)} · "
        f"P5 Email {_s(cfg.get('emailEnabled', True) is not False)}"
    ]


# ── run resolution (titles, not ids) ─────────────────────────────────────────

def _fetch_runs(active: bool = False, limit: int = 20,
                via_agent: bool = False) -> tuple[int, dict, list]:
    """GET /updates → (http_code, body, runs). Runs are newest-first. With
    ``via_agent`` the bridge restricts to agent-started runs AND computes
    per-phase updates (lazily minting the permanent SR links) — used by the
    `updates` command so it streams the same clean per-phase links the watchdog
    does. The plain (resolution) calls leave it off to avoid needless minting."""
    q = "/updates?active=1" if active else f"/updates?limit={limit}"
    if via_agent:
        q += "&via=agent"
    code, body = _get(q)
    runs = body.get("runs", []) if isinstance(body, dict) else []
    return code, body, runs


def _pick_run(runs: list, arg: str | None, *, prefer_active: bool = False) -> dict | None:
    """Resolve an optional run arg to a run row. None → newest (active-first when
    prefer_active); else the newest case-insensitive match on runId / title /
    topic (runs are newest-first, so the first match is the most recent)."""
    if not runs:
        return None
    if arg:
        a = arg.strip().lower()
        for r in runs:  # exact id wins
            if a == (r.get("runId") or "").lower():
                return r
        for r in runs:  # else newest title/topic match
            if a in (r.get("title") or "").lower() or a in (r.get("topic") or "").lower():
                return r
        return None
    if prefer_active:
        for r in runs:
            if r.get("status") in ("queued", "ongoing"):
                return r
    return runs[0]


#: What a bare verb would have done, for the sentence that says it did not.
_NOT_DONE = {"stop": "stopped", "pause": "paused", "resume": "resumed",
             "retry": "retried", "skip": "skipped"}


def _refuse_to_guess(body: dict, verb: str) -> tuple[dict, list[str]] | None:
    """(payload, chat lines) refusing a BARE run verb — or None to go ahead.

    ⛔⛔ A BARE VERB MUST NOT SILENTLY PICK A DIFFERENT RUN. An incognito run is
    in no list the chat can read, so a bare "stop" said right after starting one
    used to stop the newest run the chat COULD see — the person's ordinary run —
    and leave the one they meant going. Stop cannot be undone. The bridge now
    says a run it cannot show is still going (`hiddenLiveRun`), and a bare verb
    then asks instead of choosing.

    ⭐ ONE RULE FOR ALL FIVE VERBS. It refuses even where the hidden run could not
    have been the one meant (a bare resume while it is running): telling which
    verb could have meant which run would need the hidden run's age and state in
    the chat, and those are exactly what the chat must not hold.

    ⛔ IT NAMES NOTHING OF THE HIDDEN RUN beyond "a run you can’t manage from
    chat" — no topic, no id, not how many. It names the runs it CAN manage
    (`live` on each row: the bridge's own test, so the two cannot disagree).

    ⛔ `is True`, NOT TRUTHINESS: an older bridge does not send the field, and a
    run it lists is one this client may act on exactly as it always did."""
    if not (isinstance(body, dict) and body.get("hiddenLiveRun") is True):
        return None
    mine = [r for r in body.get("runs") or [] if isinstance(r, dict) and r.get("live") is True]
    lines = [f"I can’t tell which run you mean, so I haven’t {_NOT_DONE[verb]} anything."]
    if mine:
        lines.append("You have a run you can’t manage from chat. These are the ones I can:")
        lines += [f"  • “{r.get('title') or r.get('topic') or r.get('runId')}” — "
                  f"{r.get('status') or '?'}" for r in mine]
        lines.append("Tell me which one by name.")
    else:
        lines.append("You have a run you can’t manage from chat, and no other run in progress.")
    lines += _agent_directive_block([
        f"Do not {verb} any run until the person names one. Never pick one of "
        "these runs for them — the run they meant may be one chat cannot manage."])
    payload = {"ok": False, "reason": "which_run", "error": lines[0],
               "runs": [{"runId": r.get("runId"), "title": r.get("title"),
                         "status": r.get("status")} for r in mine]}
    return payload, lines


def _device_names() -> dict:
    """{deviceId: friendly name} from /devices (name → hostname → id). Empty on failure."""
    code, body = _get("/devices")
    if code != 200 or not isinstance(body, dict):
        return {}
    return {d.get("id"): (d.get("name") or d.get("hostname") or d.get("id"))
            for d in body.get("devices", [])}


def _dev_label(d: dict) -> str:
    return d.get("name") or d.get("hostname") or d.get("id") or "device"


def _resolve_device_arg(arg: str) -> tuple[dict | None, list[str]]:
    """A device NAME (or id) → the device dict. Exact id wins; else exact
    case-insensitive name/hostname; else a unique substring match. Returns
    (device, chat-lines-to-print-on-failure) — exactly one is set."""
    code, body = _get("/devices")
    if code != 200 or not isinstance(body, dict):
        return None, [f"✗ {body.get('error', code)}"]
    devices = body.get("devices", [])
    if not devices:
        # ⛔ WRAPPED HERE, AT THE SOURCE, because every caller emits these lines
        # as its whole message (device-use, device-remove, device-visibility) or
        # last (send-logs' `_say`) — so the relay rule is still the final block.
        return None, _with_empty_state_relay(_no_device_lines())
    # ⛔ THE QUOTES COME OFF. The picker this client prints ends with
    # 'Just say: use “<name>”.', so the reply people are TOLD to send arrives
    # wrapped — and a quoted name matched nothing here, name or substring, so
    # following the instruction on screen produced "No device matching".
    a = arg.strip().strip("“”\"'‘’").strip().lower()
    for d in devices:
        if a == (d.get("id") or "").lower():
            return d, []
    exact = [d for d in devices
             if a == (d.get("name") or "").lower() or a == (d.get("hostname") or "").lower()]
    if len(exact) == 1:
        return exact[0], []
    sub = exact or [d for d in devices
                    if a in (d.get("name") or "").lower() or a in (d.get("hostname") or "").lower()]
    if len(sub) == 1:
        return sub[0], []
    if sub:
        names = ", ".join(f"“{_dev_label(d)}”" for d in sub)
        return None, [f"That matches more than one device ({names}) — tell me the full name."]
    return None, [f"No device matching “{arg}” — ask to see your devices."]


def _attention_lines(r: dict) -> list[str]:
    """Chat lines for a run that needs the user (C1). `r` is a run row (/updates)
    or a full research doc (/research/{id}); a current bridge puts
    attention / attentionAction / attentionDetails / attentionOffers on BOTH.

    ⛔ The action line comes from the BRIDGE, which classifies the card. It used
    to be guessed here from `pendingDecision.kind` — and three different
    situations share the `login_required` literal, so a run that needed an
    Anthropic API key was told to "sign in on the device". The legacy branch
    below still runs against an older bridge; these scripts are copied out at
    connect time and can sit a release behind."""
    pd = r.get("pendingDecision")
    text = r.get("attention")
    if not text and isinstance(pd, dict) and pd:
        text = pd.get("title") or pd.get("message") or pd.get("reason")
    if not text and not r.get("needsAttention"):
        return []
    lines = [f"  ⚠ Needs you: {text or 'a decision is needed'}"]
    det = r.get("attentionDetails") or (pd.get("details") if isinstance(pd, dict) else None)
    if det:
        lines.append(f"  ↳ {det}")
    action = r.get("attentionAction")
    if action:
        lines.append(f"  → {action}")
        return lines
    # ── Legacy: an older bridge ships no attentionAction. Keep today's guess,
    # minus the one case it got outright wrong.
    kind = pd.get("kind") if isinstance(pd, dict) else None
    if kind == "login_required" and isinstance(pd, dict) and pd.get("envErrors"):
        lines.append("  → add an Anthropic API key on the device (Account → API "
                     "Config), then tell me to retry.")
    elif kind == "login_required":
        lines.append("  → sign in on the device, then tell me to retry.")
    elif kind == "human_verification_required":
        lines.append("  → finish the check on the device, then tell me to retry.")
    else:
        lines.append("  → tell me to retry to resume, or skip to move past it (or open the app).")
    return lines


def _refuse_if_not_offered(run: dict, verb: str) -> list[str] | None:
    """Chat lines refusing a verb this run's card does not offer — or None to go
    ahead. ⛔ ABSENT `attentionOffers` MEANS AN OLDER BRIDGE, NOT "NEITHER".
    Conflating the two makes a current script refuse everything against an older
    bridge, so the check is `is None`, never falsiness."""
    # ⛔⛔ A RUN WITH NO BLOCKER AT ALL ALSO CARRIES AN EMPTY OFFERS LIST, and it
    # means something completely different: not "this card has no Retry" but
    # "there is no card". Refusing here told somebody whose run was streaming
    # along fine that it had no Retry and they should open the app — inventing a
    # problem. The bridge already has the right sentence for that state
    # ("nothing to resolve — this run isn't waiting on a decision"), so let the
    # request through and relay it. ⛔ The fix is HERE and not on the wire: the
    # absent-vs-empty distinction `attentionOffers` carries is load-bearing for
    # version skew, and making it None for an unblocked run would collapse it.
    if not run.get("needsAttention"):
        return None
    offers = run.get("attentionOffers")
    if offers is None or verb in offers:
        return None
    title = run.get("title") or run.get("topic") or run.get("runId")
    act = run.get("attentionAction") or "Open the app to act on it."
    label = "Retry" if verb == "retry" else "Skip"
    return [f"“{title}” has no {label} right now.", f"  → {act}"]


# ── per-chat streaming watchdog (arm-stream) ─────────────────────────────────

def _origin_from_env() -> dict | None:
    """The chat this skill subprocess was invoked from, from the gateway's
    per-session env (HERMES_SESSION_PLATFORM / _CHAT_ID / _THREAD_ID). The
    gateway bridges those contextvars into a FOREGROUND skill subprocess's env
    (tools/environments/local.py _make_run_env); a background / cron subprocess
    does NOT get them — which is exactly why the per-chat watchdog bakes its
    origin into a generated shim instead of reading the env. Returns {platform,
    chat_id[, thread_id]} only when both platform and chat are known, else None."""
    platform = (os.environ.get("HERMES_SESSION_PLATFORM") or "").strip()
    chat_id = (os.environ.get("HERMES_SESSION_CHAT_ID") or "").strip()
    thread_id = (os.environ.get("HERMES_SESSION_THREAD_ID") or "").strip()
    if not platform or not chat_id:
        return None
    out = {"platform": platform, "chat_id": chat_id}
    if thread_id:
        out["thread_id"] = thread_id
    return out


def _origin_slug(origin: dict) -> str:
    """A short, filesystem-safe id for a chat origin: a readable platform prefix
    plus a hash of the full (platform, chat, thread) tuple — so two chats never
    collide and odd chat-id characters (negative group ids, etc.) never reach a
    filename. MUST stay identical to sr_attention_poll._origin_slug so a shim
    (sr_poll_<slug>.py) and its de-dup state (.sr_poll_<slug>.state.json) pair up."""
    platform = re.sub(r"[^A-Za-z0-9]", "", (origin.get("platform") or "")).lower()[:16] or "chat"
    key = "\x00".join((origin.get("platform") or "", origin.get("chat_id") or "",
                       origin.get("thread_id") or ""))
    return f"{platform}_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"


_WATCHDOG_NAME = "sr_attention_poll.py"


def _scripts_dir_candidates() -> "list[Path]":
    """Every plausible <HERMES_HOME>/scripts, most authoritative first.

    ⛔⛔ THE OLD DERIVATION FOLLOWED A SYMLINK STRAIGHT OUT OF HERMES_HOME, and it
    did so AHEAD of $HERMES_HOME, so the runtime's own declaration of its home was
    never consulted. It took `Path(__file__).resolve()` and walked up four parents.
    On a host whose skills dir is a symlink into a separate state repo —
    `~/.hermes/skills -> ~/rocky/skills`, which is the owner's own box — `resolve()`
    rewrites the path, so the walk yields `~/rocky/scripts` (empty) and
    `_cron_jobs_file` yields `~/rocky/cron/jobs.json`, a store the live gateway
    never reads.

    ⛔ AND THE WHOLE FEATURE RIDES ON THIS ONE ANSWER. `_cron_jobs_file` hangs off
    its parent, so getting it wrong means no shim, no cron row, and therefore no run
    progress, no completion, and no "✓ signed in" after a successful browser
    approval. Measured live 2026-09-19: the login succeeded, the bridge parked the
    announce, and the chat said nothing until the owner asked.

    ⭐ `connect.hermes_scripts_dir()` computes the SAME directory from `Path.home()`
    and never resolves — which is why the INSTALL landed correctly while the SKILL
    looked somewhere else. The two must not be able to disagree again, so the
    candidates below are ordered by how hard they are to fool:

      1. `$HERMES_HOME` — the runtime's own declaration, exported by the gateway
         into every child. Symlink-proof by construction.
      2. The install path WITHOUT resolving symlinks. `os.path.abspath` is purely
         lexical, so this is the path the runtime actually addressed us by.
      3. The RESOLVED path — the old behaviour, still right when the physical
         location really is the home.
    """
    out: "list[Path]" = []

    def add(p: Path) -> None:
        if p not in out:
            out.append(p)

    env = (os.environ.get("HERMES_HOME") or "").strip()
    if env:
        add(Path(env) / "scripts")
    for here in (Path(os.path.abspath(__file__)), Path(__file__).resolve()):
        if len(here.parents) >= 5 and here.parents[1].name == "sr":
            add(here.parents[4] / "scripts")
    return out


def _scripts_dir() -> Path:
    """The <HERMES_HOME>/scripts dir where the watchdog + its shims live (the cronjob
    tool only accepts scripts from there, and a shim imports `sr_attention_poll`
    from beside itself).

    ⭐ PICK THE CANDIDATE THAT ACTUALLY HOLDS THE WATCHDOG. Presence on disk is the
    one piece of evidence a symlink or an unusual layout cannot forge. If none holds
    it, return the most authoritative candidate anyway, so `_write_poll_shim` still
    surfaces its clean "re-run `agent connect`" error against the right directory.

    ⚠ THE LAST RESORT IS THIS BUNDLE'S OWN SCRIPTS DIR, and that is a poor answer —
    it holds a watchdog copy but is a path the cron tool rejects, so the failure
    arrives as a confusing cron error rather than a clear one. It is reached only
    when NOTHING identifies a home: no `$HERMES_HOME`, and an install path that is
    not the deployed `<home>/skills/research/sr/scripts/` shape — i.e. running this
    file straight out of a source checkout, which is not a deployment. Unchanged
    from the previous implementation; kept because with no home identified there is
    nothing better to return."""
    cands = _scripts_dir_candidates()
    for c in cands:
        if (c / _WATCHDOG_NAME).is_file():
            return c
    return cands[0] if cands else Path(__file__).resolve().parent


# A tiny generated shim: the cron `no_agent` runner can't pass args or see the
# session env, so the chat origin is baked in here and the shared watchdog does
# the work. {origin!r} renders a plain Python dict literal (only safe str values).
_SHIM_TEMPLATE = '''#!/usr/bin/env python3
"""Per-chat Super Research streaming watchdog (auto-generated by `sr.py arm-stream`).

Bakes in one chat's origin so the gateway cron job — which can neither take args
nor read the session env — streams ONLY that chat's runs, then delegates to the
shared sr_attention_poll watchdog. Safe to delete; `agent disconnect` cleans it
up along with its .sr_poll_*.state.json de-dup file."""
import sr_attention_poll

ORIGIN = {origin!r}

if __name__ == "__main__":
    raise SystemExit(sr_attention_poll.main(origin=ORIGIN))
'''


def _write_poll_shim(scripts_dir: Path, name: str, origin: dict) -> str | None:
    """Write the per-chat shim next to sr_attention_poll.py. Returns an error
    message on failure (so arm-stream can relay it), else None on success."""
    try:
        scripts_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"couldn't reach the scripts dir ({type(e).__name__})"
    if not (scripts_dir / "sr_attention_poll.py").is_file():
        return "the watchdog script isn't installed — re-run `agent connect` on the host"
    try:
        (scripts_dir / name).write_text(_SHIM_TEMPLATE.format(origin=origin), encoding="utf-8")
    except OSError as e:
        return f"couldn't write the watchdog shim ({type(e).__name__})"
    return None


# ── deterministic watchdog arming ─────────────────────────────────────────────
# The watchdog cron USED to be armed by the chat AI acting on a `cronjob: create`
# directive this skill printed. That was the recurring failure: a non-deterministic
# LLM armed it inconsistently, so run progress + the 🎉 completion + the "✓ signed
# in" announce (all ride this one cron) silently never posted. But this skill runs
# as a FOREGROUND chat subprocess, so it knows the chat origin (_origin_from_env)
# AND can reach the runtime's cron store — it arms the job ITSELF by writing the row
# straight into <HERMES_HOME>/cron/jobs.json, the exact shape the runtime's own
# cronjob tool produces. Verified against the live Hermes engine: the scheduler
# re-reads jobs.json every tick (no in-memory registry), a hand-written no_agent +
# schedule row is picked up and fires, and deliver="origin" with a baked origin
# routes each tick's output to the arming chat. No LLM in the arming loop.


def _cron_jobs_file() -> Path:
    """<HERMES_HOME>/cron/jobs.json — the runtime's durable cron store, a sibling of
    the scripts dir where this skill's watchdog + shims live."""
    return _scripts_dir().parent / "cron" / "jobs.json"


def _cron_now() -> str:
    """An ISO timestamp for cron bookkeeping. Used as ``next_run_at`` so the job is
    due on the very next tick — NOT a time in the past, which the runtime would
    fast-forward (skip) once it falls outside the catch-up grace window."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _build_stream_cron_job(script_name: str, job_name: str, origin: dict | None,
                           schedule: dict) -> dict:
    """A well-formed Hermes cron-job row (mirrors cron.jobs.create_job's shape).
    ``deliver="origin"`` + the baked ``origin`` routes each tick's output to the
    chat that armed it (resolved at fire time from ``job["origin"]``); no origin →
    ``"local"`` (the caller only writes directly when an origin is present, so this
    branch stays correct). ``next_run_at`` ≈ now so it's due within the scheduler's
    grace window and fires on the very next tick — the start of this minute for a
    cron expression (`_first_run_at`); ``repeat.times=None`` = forever, so
    mark_job_run never auto-removes it."""
    now = _cron_now()
    return {
        "id": uuid.uuid4().hex[:12],   # REQUIRED — subscripted in Hermes' due-scan
        "name": job_name,
        "prompt": "",
        "skills": [],
        "skill": None,
        "model": None,
        "provider": None,
        "base_url": None,
        "script": script_name,
        "no_agent": True,              # the script IS the job — no LLM, no tokens
        "context_from": None,
        "schedule": schedule,
        "schedule_display": schedule.get("display", ""),
        "repeat": {"times": None, "completed": 0},
        "enabled": True,
        "state": "scheduled",
        "paused_at": None,
        "paused_reason": None,
        "created_at": now,
        "next_run_at": _first_run_at(schedule),
        "last_run_at": None,
        "last_status": None,
        "last_error": None,
        "last_delivery_error": None,
        "deliver": "origin" if origin else "local",
        "origin": origin,
        "enabled_toolsets": None,
        "workdir": None,
    }


def _arm_stream_cron(script_name: str, job_name: str, origin: dict | None,
                     schedule: dict) -> bool:
    """Write the watchdog cron row into <HERMES_HOME>/cron/jobs.json deterministically
    — no dependence on the chat AI issuing cronjob:create. Idempotent BY NAME: a
    RUNNABLE job of this name is left untouched (except, once, by the watcher
    schedule migration — `_migrate_stream_schedules`), and a disabled/paused one is revived
    in place rather than duplicated (create has no dedupe, so a blind re-append would
    accumulate duplicates → the runtime's later name lookups raise
    AmbiguousJobReference). Serialized against the gateway via the
    same advisory flock (<cron>/.jobs.lock) and written atomically (temp + replace),
    mirroring cron.jobs. Returns True when the job is present after the call (added
    or already there); False on any failure, so the caller can fall back to the AI
    directive."""
    jobs_file = _cron_jobs_file()
    cron_dir = jobs_file.parent
    lock_fd = None
    try:
        cron_dir.mkdir(parents=True, exist_ok=True)
        try:
            lock_fd = open(cron_dir / ".jobs.lock", "a+", encoding="utf-8")
        except OSError:
            lock_fd = None  # best-effort; proceed without the cross-process lock
        if lock_fd is not None and fcntl is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
            except OSError:
                pass
        try:
            data = json.loads(jobs_file.read_text("utf-8"))
        except FileNotFoundError:
            data = {"jobs": []}
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            return False
        existing = next((j for j in data["jobs"]
                         if isinstance(j, dict) and j.get("name") == job_name), None)
        # ⭐ THE ONE-TIME SCHEDULE MIGRATION (owner, 2026-09-25) — every watcher
        # row on this host, not only this chat's, because the arm is the only
        # moment this client holds the store. See `_migrate_stream_schedules`.
        moved = (_migrate_stream_schedules(data["jobs"], schedule)
                 if _is_stream_job_name(job_name) else [])
        if existing is not None:
            # Present — but "present" only counts as ARMED if it can actually run. A
            # disabled/paused row is skipped by the runtime's due-scan before any
            # next-run recovery, so treating it as armed would leave the chat silent
            # with no way back (a re-arm would keep finding it). Revive it in place
            # instead of appending a duplicate (duplicates break name lookups).
            if existing.get("enabled", True) and existing.get("state") != "paused":
                if not moved:
                    return True  # genuinely armed — idempotent no-op
            else:
                existing.update({"enabled": True, "state": "scheduled", "paused_at": None,
                                 "paused_reason": None,
                                 # due now, inside the grace window
                                 "next_run_at": _first_run_at(existing.get("schedule"))})
        else:
            data["jobs"].append(_build_stream_cron_job(script_name, job_name, origin, schedule))
        # Per-process temp name. Several writers touch this file — this arming
        # path on every send, plus the watchdog's and update-notice teardowns —
        # and a single shared temp name lets two of them interleave write and
        # rename, so one publishes the other's half-written jobs list.
        tmp = jobs_file.with_suffix(".json.sr-tmp.%d" % os.getpid())
        tmp.write_text(json.dumps(data), "utf-8")
        try:
            os.chmod(tmp, 0o600)  # the cron store is owner-only; os.replace carries
        except OSError:           # the temp file's mode onto jobs.json
            pass
        os.replace(tmp, jobs_file)  # atomic; Hermes re-reads jobs.json each tick
        if moved:
            _watcher_log(f"arm {job_name}: moved {len(moved)} watcher row(s) to "
                         f"{schedule.get('display', '')!r}: {', '.join(moved)}")
        if existing is None:
            _watcher_log(f"arm {job_name}: new row, schedule "
                         f"{schedule.get('display', '')!r}")
        return True
    except OSError:
        return False
    finally:
        if lock_fd is not None:
            try:
                if fcntl is not None:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            lock_fd.close()


# INTERVAL, AS THE FALLBACK — not a cron expression. Both persist identically (the
# runtime stores whatever we write and re-reads it each tick), but a cron-expr
# schedule needs the runtime's OPTIONAL croniter dependency: without it, next-run
# computation returns None, so the job would fire ONCE and then go permanently
# silent — the exact failure this fix exists to eliminate. An interval schedule
# never touches croniter, so it ticks forever either way. It is what a runtime gets
# whenever `_runtime_has_croniter` cannot CONFIRM croniter (see below).
_STREAM_SCHEDULE = {"kind": "interval", "minutes": 1, "display": "every 1m"}
_UPDATE_NOTICE_SCHEDULE = {"kind": "interval", "minutes": 1440, "display": "every 1440m"}

# ⭐⭐ "EVERY 1m" RAN EVERY ~2 MINUTES, SO WHERE THE RUNTIME CAN COMPUTE A CRON
# EXPRESSION THE WATCHER GETS ONE (owner, 2026-09-25). Hermes counts an interval
# from the moment a run FINISHES and its due check is strict, so a run that ends a
# second after its claim always misses the next 60-second pass: measured on
# 2026-09-24, the owner's watcher ran every 113 s on average (72–154 s), and the
# "✓ Signed in" waited a whole extra pass before the watcher even picked it up.
# `* * * * *` is anchored to minute boundaries instead, so every pass finds it due.
# ⛔ `next_run_at` IS ROUNDED DOWN TO THE MINUTE FOR THIS SHAPE (`_first_run_at`).
# Hermes reads an off-boundary next_run_at on a cron row as a hand-edited
# expression and re-anchors it WITHOUT firing — it would skip the first run, which
# is exactly the one that carries a sign-in. The floor is at most 59 s in the past,
# inside the runtime's 120 s catch-up grace window.
_STREAM_CRON_SCHEDULE = {"kind": "cron", "expr": "* * * * *", "display": "* * * * *"}


def _hermes_croniter_path() -> "str | None":
    """Where the chat runtime's OWN install keeps croniter, or None if that cannot
    be confirmed.

    ⛔ THE RUNTIME'S INTERPRETER, NOT OURS. The gateway computes next runs in its
    own environment; this script may be run by a different Python altogether, so
    importing croniter here would prove nothing. The `hermes` command leads to that
    environment: its real path (the owner's is ~/.local/bin/hermes →
    ~/hermes-agent/.venv/bin/hermes) and its shebang both sit inside the virtualenv
    whose site-packages we look in. Read-only; anything unusual answers None, which
    keeps the interval — the direction that can never go silent."""
    import glob
    import shutil
    clis: "list[str]" = []
    found = shutil.which("hermes")
    if found:
        clis.append(found)
    clis.append(str(Path.home() / ".local" / "bin" / "hermes"))
    roots: "list[Path]" = []
    for cli in clis:
        try:
            if not os.path.isfile(cli):
                continue
            real = Path(os.path.realpath(cli))
            roots.append(real.parent.parent)
            with open(real, "rb") as fh:
                first = fh.readline(512)
        except OSError:
            continue
        if first.startswith(b"#!"):
            interp = first[2:].strip().split(b" ")[0].decode("utf-8", "replace")
            # ⛔ NOT resolved: a venv's python is usually a symlink to the system
            # one, and following it would leave the venv we are looking for.
            if interp and not interp.endswith("/env"):
                roots.append(Path(interp).parent.parent)
    for root in dict.fromkeys(roots):
        for sp in (glob.glob(str(root / "lib" / "python*" / "site-packages"))
                   + [str(root / "Lib" / "site-packages")]):
            for mod in (Path(sp) / "croniter" / "__init__.py", Path(sp) / "croniter.py"):
                if mod.is_file():
                    return str(mod)
    return None


def _runtime_has_croniter() -> bool:
    return _hermes_croniter_path() is not None


def _stream_schedule() -> dict:
    """The watcher's schedule on THIS host: a minute-anchored cron expression
    where the runtime can compute one, the interval everywhere else."""
    return dict(_STREAM_CRON_SCHEDULE if _runtime_has_croniter() else _STREAM_SCHEDULE)


def _first_run_at(schedule: "dict | None") -> str:
    """`next_run_at` for a row being armed, revived or migrated: now for an
    interval, the start of the current minute for a cron expression (see
    `_STREAM_CRON_SCHEDULE` for why it must not be off the boundary)."""
    if isinstance(schedule, dict) and schedule.get("kind") == "cron":
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).replace(second=0, microsecond=0).isoformat()
    return _cron_now()


def _is_stream_job_name(name: object) -> bool:
    return isinstance(name, str) and (name == "sr-stream" or name.startswith("sr-stream-"))


def _schedule_key(schedule: object) -> "tuple | None":
    """The two watcher schedules this client has ever written, as comparable keys;
    None for anything else (a hand-edited schedule, which migration leaves alone)."""
    if not isinstance(schedule, dict):
        return None
    if schedule.get("kind") == "interval" and schedule.get("minutes") in (1, 1.0):
        return ("interval", 1)
    if schedule.get("kind") == "cron" and schedule.get("expr") == "* * * * *":
        return ("cron", "* * * * *")
    return None


def _migrate_stream_schedules(jobs: list, want: dict) -> "list[str]":
    """Move every watcher row still on the OTHER schedule this client writes onto
    ``want``, in place; returns the names it moved.

    ⭐ ONCE PER ROW, BY CONSTRUCTION. Arming used to leave a runnable row untouched
    ("idempotent by name"), so every watcher already armed would have kept its
    ~2-minute interval forever. A row that already has ``want`` is not touched
    again, so this runs once per row and then never. It works in both directions:
    a cron row on a host that no longer has croniter goes BACK to the interval,
    because a cron row there would fire once and then never again.
    ⛔ A schedule this client never wrote (somebody hand-edited it) is left alone."""
    want_key = _schedule_key(want)
    moved: "list[str]" = []
    if want_key is None:
        return moved
    for job in jobs:
        if not isinstance(job, dict) or not _is_stream_job_name(job.get("name")):
            continue
        have = _schedule_key(job.get("schedule"))
        if have is None or have == want_key:
            continue
        job["schedule"] = dict(want)
        job["schedule_display"] = want.get("display", "")
        job["next_run_at"] = _first_run_at(want)
        moved.append(str(job.get("name")))
    return moved


def _watcher_log_path() -> Path:
    """The watcher's own log — a FILE, because its stdout IS the chat message.
    `SUPER_AGENT_WATCHER_LOG` points it elsewhere (the test suite does, so no test
    writes into a real home). MUST match sr_attention_poll._log_path."""
    raw = (os.environ.get("SUPER_AGENT_WATCHER_LOG") or "").strip()
    return Path(raw) if raw else Path.home() / ".super-agent" / "watcher.log"


def _watcher_log(msg: str) -> None:
    """Append one line to the watcher's log. Never raises, never prints: this runs
    inside a chat reply, and a logging failure is not the person's problem."""
    try:
        path = _watcher_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        with open(path, "ab") as fh:
            fh.write(f"{stamp} sr.py[{os.getpid()}] {msg}\n".encode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — best-effort diagnostics only
        pass


# ── commands ────────────────────────────────────────────────────────────────

# ⭐⭐ A LOGIN ANSWER IS ABOUT LOGIN ONLY (owner, 2026-09-25). On 2026-09-24 one
# sign-in reached one chat three ways inside two minutes — "✓ Connected as … —
# you're all set", the watcher's "Just tell me what to research", and a run-on
# "Add a computer … Or ask me for a public computer" — to somebody who had only
# asked whether they were logged in, with advice that contradicted itself. Every
# reply that says somebody is signed in now opens with ONE line, and for a plain
# sign-in it IS that line: `_connected_msg`. Device content belongs to device
# situations — a research with nowhere to run, adding or listing computers, a
# sign-in whose waiting topic has nowhere to run — and keeps its separate blocks
# there.
_SIGNED_OUT_LINE = "Not signed in — tell me to log you in and I'll send a link."


def _ack_signed_in(reader: str, *, with_news: bool = False) -> "tuple[int, dict]":
    """Tell the bridge this reply is about to say "signed in" (`POST /signin/ack`).

    ⭐⭐ ONE "ALREADY TOLD" RECORD (owner, 2026-09-25). The watcher and the chat's
    own answer each announced the same sign-in, 34 s apart, because nothing
    recorded that the person had been told. The ack TAKES this chat's parked note
    (so the watcher finds nothing to repeat), seals the bridge's watermark at this
    sign-in (so nothing re-mints it), and records who said it. Memory and
    prefs.json only on the bridge's side, so even a status check can afford it.

    ⛔ ``with_news`` ONLY FROM A REPLY THAT RENDERS THE NOTE. A note that says what
    the bridge DID with a waiting research ("Started X on Y", "X has nowhere to
    run") is handed only to a caller that promises to relay it; any other caller
    leaves it for the watcher, so a plain "✓ Signed in" can never swallow it.

    Scoped to THIS chat whenever the runtime says which one it is, so a note
    addressed to another chat is never taken. Returns the bridge's (code, body):
    401 means the session ended — nothing may say "signed in" — and 404 is an
    older bridge without the route."""
    body: dict = {"reader": reader}
    origin = _origin_from_env()
    if origin:
        body["platform"] = origin.get("platform", "")
        body["chat"] = origin.get("chat_id", "")
    if with_news:
        body["withNews"] = True
    code, out = _post("/signin/ack", body)
    return code, (out if isinstance(out, dict) else {})


def _already_signed_in() -> "tuple[str | None, dict]":
    """``(line, status body)`` when the account is signed in right now, else
    ``(None, {})`` — the check `login` makes before it starts anything."""
    code, body = _get("/status")
    if code != 200 or not isinstance(body, dict) or not body.get("authed"):
        return None, {}
    acode, ack = _ack_signed_in("login")
    if acode == 401:
        return None, {}  # it ended between the two reads — sign in afresh
    who = (ack.get("email") if acode == 200 else None) or body.get("email") or body.get("uid")
    return (f"You're already signed in as {who} — say log out to switch accounts.",
            body)


def cmd_login(args) -> int:
    # ⭐⭐ ALREADY SIGNED IN → SAY SO AND START NOTHING (owner, 2026-09-25). A new
    # sign-in used to start regardless, and starting one makes the bridge throw
    # away the parked sign-in note — so "log me in" from somebody already signed in
    # destroyed whatever that note was still holding, and quietly switched
    # accounts in one step nobody had asked for. Switching is two deliberate steps
    # now: log out, then log in. The chat's watcher is still armed below — the
    # same idempotent arm as a fresh sign-in, so a chat without one gets it.
    already, status = _already_signed_in()
    if already:
        body = status
        lines = [already]
    else:
        payload = {"runtime": args.runtime or "", "label": args.label or ""}
        origin = _origin_from_env()
        if origin:
            payload["origin"] = origin
        code, body = _post("/login/remote/start", payload)
        if code != 200:
            return _emit(body, args.json, [f"✗ couldn't start sign-in: {body.get('error', code)}"], _fail_code(code))
        lines = [
            "Log in here:",
            f"  {body.get('verifyUrl')}",
            "Tap Authenticate when the page opens — you'll connect automatically.",
        ]
    # Arm THIS chat's watchdog so the moment the browser approval is captured the
    # bridge's "✓ signed in" lands here on its own — no need to poll for completion.
    arm_lines, _payload, arm_rc = _prepare_stream_arm()
    if arm_rc == 0 and arm_lines:
        lines += _agent_directive_block(arm_lines)
    elif arm_rc != 0 and arm_lines:
        # ⛔⛔ DO NOT SWALLOW THIS. `_prepare_stream_arm` returns rc=1 with a single
        # "✗ …" line when the watchdog could not be armed, and this branch used to
        # drop it — so a sign-in whose announce could never be delivered looked
        # exactly like one that would arrive momentarily. The user waits, nothing
        # comes, and the only diagnostic was computed and thrown away. Measured
        # live 2026-09-19. Relayed to the person, not as an AI directive: there is
        # nothing for the model to DO with it, and it names the repair.
        lines += arm_lines
    return _emit(body, args.json, lines)


def _claim_signed_in_announce() -> dict:
    """TAKE the parked sign-in announce, because we are about to tell them ourselves.

    ⛔⛔ WITHOUT THIS, `login-done` TOLD THEM AND LEFT THE NOTE SITTING THERE, so the
    watchdog said the same news again a minute later — and the note is the ONLY place
    that records what the bridge DID about the research they asked for. The owner's
    own fleet transcript is this exact shape: 78 seconds of silence, the person asks
    "started the super research?", `login-done` answers "they are signed in" and
    nothing else, and "which of your three computers?" had to be worked out by hand
    from a separate command. That question was already minted, parked, and thrown away.

    ⭐ THE FLEET'S FORK ALREADY DOES THIS and this copy did not — the fork has both
    the claim and the outcome renderer, and the shipped wheel had neither. This is the
    wheel catching up with the client that overtook it.

    ⭐ SCOPED WHEN WE KNOW OUR CHAT. `?via=agent` is the bridge's only take trigger;
    adding platform+chat is what lets it hand over an ADDRESSED note — the ordinary
    case, since `login` posts this chat's address. Without the scope this reads as the
    account-wide watchdog and an addressed note is (correctly) refused, so we would
    take nothing and the double-announce would survive the fix.

    ⚠ THE FALLBACK SINCE 2026-09-25, NOT THE PATH. `login-done` takes the note
    through `POST /signin/ack` (`_ack_signed_in`), which also seals the watermark
    and records the telling, without this read's Firestore work. This runs only
    against an older bridge that answers the ack with 404; `reader` names us in
    its log (an older bridge ignores it).

    Returns {} on any failure: a courtesy line is never worth failing a sign-in over.
    """
    q = "/updates?via=agent&limit=1&reader=login-done"
    origin = _origin_from_env()
    if origin:
        q += "&platform=" + urllib.parse.quote(origin.get("platform", ""), safe="")
        q += "&chat=" + urllib.parse.quote(origin.get("chat_id", ""), safe="")
    try:
        code, body = _get(q)
    except Exception:
        return {}
    if code != 200 or not isinstance(body, dict):
        return {}
    note = body.get("signedIn")
    return note if isinstance(note, dict) else {}


def _not_signed_in_lines(body: dict) -> "list[str]":
    """What `status-account` (and `login-done`, when there is no sign-in to poll)
    says for an account that is NOT signed in, from a `/status` body."""
    if body.get("remoteLogin") == "pending":
        # A sign-in is mid-flight: approve it in the browser and the bridge
        # captures it automatically (no second command needed) — #848.
        return ["A sign-in is in progress — approve it in your browser; you'll connect automatically."]
    if body.get("remoteLogin") in ("error", "expired"):
        return ["The last sign-in didn't complete — just ask me to log you in again."]
    return [_SIGNED_OUT_LINE]


def _signed_in_reply(args, body: dict, who, topic: str = "") -> int:
    """`login-done`'s answer once the account IS signed in: the sign-in line, plus
    what the bridge did about a research that was waiting on it."""
    # ⭐⭐ THE ACK FIRST (owner, 2026-09-25): it hands over this chat's parked note
    # WITH its news (relayed below), seals the watermark, and records that this
    # reply told them — so the watcher has nothing left to say it again.
    acode, ack = _ack_signed_in("login-done", with_news=True)
    if acode == 401:
        # ⛔ The session ended while we were asking. Nothing may say "signed in".
        return _emit({**body, "authed": False}, args.json, [_SIGNED_OUT_LINE])
    if acode == 200:
        who = ack.get("email") or who
        note = ack.get("signedIn") if isinstance(ack.get("signedIn"), dict) else {}
    elif acode == 404:
        note = _claim_signed_in_announce()  # an older bridge, without the ack
    else:
        note = {}
    if isinstance(note, dict) and note and not note.get("email") and who:
        note = {**note, "email": who}
    # ⭐ SAY WHAT HAPPENED, IN THE NOTE'S OWN WORDS, rather than a guess assembled
    # from the poll reply. The note knows the four outcomes the poll reply cannot:
    # the bridge started it, there is nowhere to run it, several computers could
    # and none is obvious, or a topic is simply waiting. Taking it is also what
    # stops the watchdog repeating this in a minute — which is what SKILL.md has
    # always told the assistant this command does.
    #
    # ⛔ BUT ONLY WHEN THE NOTE ACTUALLY CARRIES NEWS. A plain note says nothing
    # this reply does not already say — "✓ Signed in as <email>." either way (a
    # login answer is about login only, owner 2026-09-25) — so the sign-in line
    # below is the whole answer. Taking the note still stops the double announce.
    #
    # ⛔⛔ AND ONLY FOR THE THREE OUTCOMES THE BRIDGE DECIDED, not for the note's
    # fourth case. That fourth case is the legacy fallback — *"Continue with X? Say
    # go ahead and I'll start it."* — a question aimed at the PERSON. SKILL.md's
    # "After a sign-in link" step 2 is written against the OTHER wording (*"Continuing
    # your research on X…"*) and treats it as the cue to run `research` immediately,
    # so preferring the note there swaps a cue-to-act for a question and the topic
    # can be stranded: the assistant waits for a "go ahead" the person has already
    # given. ⭐ TAKE THE NOTE EITHER WAY — taking it is what stops the watchdog
    # repeating the news, and that half is true of all four cases.
    if isinstance(note, dict) and (note.get("autoStarted")
                                   or note.get("needsDevice")
                                   or note.get("needsDeviceChoice")):
        # A bridge-decided outcome: relay it in the note's own words. `body` still
        # rides along so `--json` keeps every field the note carried.
        said = _signed_in_lines(note)
        # ⛔⛔ THE USUAL FIRST-TIME PATH: signed out, asks for research, signs
        # in, has no computer. The note's lines then END on the no-computer
        # screen and are this message's whole body, so they carry its relay
        # rule — the review that found this called it the likeliest place a
        # new person meets the screen at all.
        if note.get("needsDevice"):
            said = _with_empty_state_relay(said)
        return _emit({**body, "signedIn": note}, args.json, said)
    # ⛔⛔ AND THE TOPIC MUST BE READ BACK OFF THE NOTE, WHICH IS THE DEFECT THE
    # FIRST VERSION OF THIS GATE INTRODUCED. The note's FOURTH shape — a topic and
    # none of the three flags — is minted by `_autostart_worker` when its Firestore
    # I/O FAILS, and by then `flow.pending_topic` has already been nulled (it is
    # claimed under the lock before the worker is spawned). So the poll reply carries
    # NO topic, the gate above excludes the note, and my first version fell through
    # to a plain "you're all set": the note TAKEN, the topic destroyed, and the
    # person's research request gone. Before any of this work the note simply stayed
    # parked and the watchdog said it. **A fix that loses news the bug did not.**
    # ⭐ SKILL.md's wording, not the note's. The note's own fourth line asks the
    # PERSON ("say go ahead"); step 2 of "After a sign-in link" is written against
    # "Continuing your research on X…" and treats it as the cue to run `research`
    # immediately. Keep the cue, take the topic from wherever it survives.
    if isinstance(note, dict):
        topic = topic or str(note.get("topic") or note.get("pendingTopic") or "").strip()
    if topic:
        # The user asked to research this before signing in. Confirm + name the
        # topic; per SKILL.md "After a sign-in link" the assistant now runs
        # `research "<topic>"`, which starts it (or surfaces the no-computer
        # screen if there's no device) — a device situation, so the screen is
        # said there and not here. Two blocks: the sign-in, then the topic.
        return _emit(body, args.json, [
            _connected_msg(who),
            "",
            f"Continuing your research on “{topic}”…",
        ])
    return _emit(body, args.json, [_connected_msg(who)])


def cmd_login_wait(args) -> int:
    code, body = _post("/login/remote/poll")
    if code != 200:
        # ⛔⛔ NEVER THE BRIDGE'S OWN WORDS FOR A POLL WITH NOTHING TO POLL (owner,
        # 2026-09-25). A logout now forgets a finished sign-in flow, and a bridge
        # restart always did — and this relayed "✗ no remote login in progress —
        # POST /login/remote/start first" into the chat. Whether they are signed in
        # is the answer to "did it work?", so ask the account itself.
        return _login_state_from_status(args)
    state = body.get("state")
    if state == "connected":
        # ⛔⛔ "CONNECTED" DESCRIBES THE SIGN-IN FLOW, NOT THE SESSION (owner,
        # 2026-09-25). A flow can still read "connected" after the person logs
        # out, and this answered "✓ Connected as None — you're all set." to
        # somebody who had just signed out. `authed` is the session; it decides.
        if not body.get("authed"):
            return _emit(body, args.json, [_SIGNED_OUT_LINE])
        return _signed_in_reply(args, body, body.get("email") or body.get("uid"),
                                (body.get("pendingTopic") or "").strip())
    msg = {
        "pending": "Not approved yet — approve it in your browser; you'll connect automatically.",
        "expired": "✗ The sign-in link expired — ask me to send a fresh sign-in link.",
        "error": f"✗ Sign-in failed: {body.get('error', 'unknown')}",
    }.get(state, f"state: {state}")
    return _emit(body, args.json, [msg])


def _login_state_from_status(args) -> int:
    """`login-done` with no sign-in to poll: answer from the account's state — the
    sign-in line (with any news the note holds) or `status-account`'s own words."""
    code, body = _get("/status")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    if body.get("authed"):
        return _signed_in_reply(args, body, body.get("email") or body.get("uid"))
    return _emit(body, args.json, _not_signed_in_lines(body))


def _update_notices(body: dict) -> list[str]:
    """Proactive "a newer SKILL version is available" prompt from a /status (or
    /version) body — so the user is nudged on the welcome without having to ask.
    Backend updates are NOT nudged here anymore: the app surfaces those and the
    user updates from the app / `superresearch --update` on the host (the skill no
    longer updates the backend)."""
    out = []
    if body.get("agentUpdate"):
        out.append(f"⬆️ Super Research skill v{body['agentUpdate']} is available — say “update”.")
    return out


def _connected_msg(who) -> str:
    """THE sign-in line — the one every reply that says somebody is signed in
    opens with, and the whole of it for a plain sign-in.

    ⛔⛔ NO COMPUTERS IN IT (owner, 2026-09-25). This was "device-aware": with a
    computer it said "✓ Connected as X — you’re all set", without one it glued the
    add line and "Or ask me for a public computer you could use" onto the same
    sentence, one run-on paragraph. A login answer is about login only; the
    no-computer screen is said where there is a computer to be missing — a
    research with nowhere to run, adding or listing computers.
    ⛔ AND NEVER "as None". A flow that outlived its session used to render the
    missing email that way; with nothing to name, the line names nothing."""
    who = str(who or "").strip()
    return f"✓ Signed in{(' as ' + who) if who else ''}."


def cmd_status_account(args) -> int:
    code, body = _get("/status")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    if body.get("authed"):
        # ⭐⭐ "✓ Signed in as <email>." AND NOTHING ELSE (owner, 2026-09-25) — no
        # no-computer screen, no relay rule. Asked "am I logged in?", this used to
        # print the whole empty state glued to the sign-in line; that screen is for
        # device situations. The ack records that this reply told them, so the
        # watcher does not say it again — and it is taken WITHOUT the news a note
        # may carry, which stays for the watcher, because this reply relays none.
        acode, ack = _ack_signed_in("status-account")
        if acode == 401:
            # ⛔ It ended between the two reads: never say "signed in".
            lines = [_SIGNED_OUT_LINE]
        else:
            lines = [_connected_msg((ack.get("email") if acode == 200 else None)
                                    or body.get("email") or body.get("uid"))]
    else:
        lines = _not_signed_in_lines(body)
    lines += _update_notices(body)
    return _emit(body, args.json, lines)


def cmd_devices(args) -> int:
    code, body = _get("/devices")
    if code != 200:
        # ⛔⛔ AND THE SIGNED-OUT CASE IS NOT THE BRIDGE'S SENTENCE. Its 401 body is
        # "not signed in — run /login", a TERMINAL command, and this wave made this
        # command the answer to "I don't have a computer" — so the very people it
        # was written for were handed a slash command in a chat. The list refusals
        # already learned this; the device list had not.
        return _emit(body, args.json, [f"✗ {_signed_out_or(body.get('error', code))}"],
                     _fail_code(code))
    devices = body.get("devices", [])
    selected = body.get("selectedDeviceId")
    if not devices:
        return _emit(body, args.json, _with_empty_state_relay(_no_device_lines()))
    lines = ["Devices:"]
    for d in devices:
        mark = "→" if d.get("selected") else " "
        kind = "owned" if d.get("owned") else "shared"
        # ⛔⛔ THE SETTING IS PRINTED HERE BECAUSE THE SKILL FILE SAYS IT IS.
        # SKILL.md routes "is my computer public?" to this command and tells the
        # model the row says which — and this list printed neither word, so the
        # documented answer path landed on output that could not answer it. Only
        # on rows this account OWNS: a shared row would be reporting somebody
        # else's setting as if it were the reader's to change. ⛔ And absent
        # means private — a machine paired before 2026-09-04 carries no field.
        state = ""
        if d.get("owned"):
        # ⛔⛔ THIS READS THE BRIDGE'S ANSWER, NOT A FIRESTORE FIELD, AND THE
        # DIFFERENCE IS WHAT CARRIES IT THROUGH THE RENAME. `visibility` is
        # becoming `joinPolicy`; the bridge resolves both names into this one key
        # before any row leaves it (`_discovery_of`), so this line keeps working
        # without ever learning the new name. ⛔ Point it at a raw device document
        # and it goes silently wrong: every public computer would read private,
        # with no error anywhere.
            state = ", public" if d.get("visibility") == "public" else ", private"
        lines.append(f"  {mark} {_dev_label(d)}  ({kind}{state})")
    if not selected:
        lines.append("Tell me which one you’d like to use.")
    # ⛔⛔ A NO-CODE "add a device" NOW LANDS HERE TOO, so this branch has to
    # answer it. It used to close on a capability claim — "you can add, remove, or
    # switch devices anytime — just ask" — which, to somebody who just asked HOW
    # to add one, restates the question. The route is the shared add line; the
    # tail keeps the two verbs that route does not cover.
    # ⭐ WITH THE INSTALL LINK, BECAUSE THIS READER CAN NEED ONE TOO (owner,
    # 2026-09-24). Somebody whose only computer is shared, or who wants a second
    # one of their own, asks "add a device" and lands here; the old tail offered
    # only "paste the access code". The link costs no fetch.
    # ⛔ NOT the public list here: this is also what "which devices?" runs, and
    # the public list is a second network call on every one of those.
    lines.append(_ADD_A_COMPUTER)
    lines.append("You can remove or switch computers anytime — just ask.")
    return _emit(body, args.json, lines)


def cmd_device_use(args) -> int:
    dev, fail = _resolve_device_arg(args.device)
    if dev is None:
        return _emit({}, args.json, fail, 1)
    code, body = _post("/device/select", {"deviceId": dev.get("id")})
    if code != 200:
        return _emit(body, args.json, [f"✗ couldn't select device: {body.get('error', code)}"], _fail_code(code))
    d = body.get("device", {})
    kind = "owned" if d.get("owned") else "shared"
    return _emit(body, args.json, [f"✓ Now running on {_dev_label(d)} ({kind})."])


# Friendly wording for the web app's CLAIM route (`/api/devices/claim`) — the
# codes `device-add` can receive, and nothing else.
#
# ⛔⛔ IT USED TO SERVE `device-remove` TOO AND SHARED NOT ONE CODE WITH IT.
# `unpair-self` emits nine codes and this table holds seven; the intersection is
# EMPTY. So every single way an unlink can fail fell through to the raw
# fallback, and a person who could not unlink their machine read
# "couldn't remove the device: rotation_failed" — the one refusal in the product
# that is protecting them, delivered as a bare identifier. The unlink route has
# its own table below, and the guard in test_unlink_copy_795.py pins each table
# to its own route's codes so the shortcut cannot be taken again.
_PAIR_ERRORS = {
    # ⛔ THE ALPHABET EXCLUDES I, L, O, 0 AND 1 — the five that get confused —
    # and "8 letters/digits" told people the opposite, so somebody who typed an
    # O for a zero read a rule their input satisfied and retyped the same code.
    "invalid_code_format": "Access codes are 8 characters and never use I, L, O, 0 or 1 — check those.",
    # ⛔⛔ THE REPAIR IT NAMED MINTS A NEW COMPUTER AND LOSES ITS PEOPLE. Both of
    # these sentences sent somebody to `superresearch --pair`, which on a machine
    # that still exists does not refresh anything — it sets that machine up as a
    # NEW computer with a NEW id, and everybody it was shared with loses access.
    # The repair for a code that has run out is to press Reset again in the app,
    # which the web app's own table has said since wave 2 and this one did not.
    # ⛔ `--pair` IS STILL NAMED, and only where it is right: once the computer is
    # gone from that list there is nothing to reset and it IS a new setup.
    # ⭐ THE COMMONEST CAUSE COMES FIRST (2026-09-24): a mistyped code. A
    # first-timer who misread the code their new computer showed was sent straight
    # to reset emails they never got — re-reading the screen is the repair.
    "code_not_found": "No computer is waiting for that code — check it against "
                      "the code on that computer’s screen. If it came from a "
                      "reset email, use the newest one, or press Reset again in "
                      "Settings → Manage devices. Only if the computer isn’t "
                      "listed there, run “superresearch --pair” on it — that sets "
                      "it up as a new computer with a new id, and nobody you "
                      "shared the old one with keeps access.",
    "code_expired": "That code expired — press Reset again in Settings → Manage "
                    "devices for a new one, and use only the newest email.",
    "not_previous_owner": "That device is waiting for its previous owner to re-pair — only they can.",
    # ⛔⛔ "ask them to share it again" IS REFUSED ON EVERY PATH, and the web app's
    # own table says it too. The blocklist is consulted by claim, by the ask route
    # and by the approve route, and it is cleared only by a full Reset or an
    # owner-unlink — so a re-sent code answers `revoked_sharer` again. This file
    # already words the ask route's version correctly; this one lagged.
    "revoked_sharer": "The owner removed your access to that computer. Re-using a code "
                      "or asking again can’t change that — only they can, from the app.",
    "share_cap_reached": "That device is shared with as many people as it can hold — "
                         "ask the owner to remove someone first.",
    # ⛔ NO DURATION HERE — `_rate_limited_line` reads the one the route sent.
    "rate_limited": "",
    # ⛔ THE FIVE THIS TABLE WAS MISSING — it covered 7 of the route's 12, so a
    # third of the ways pairing can fail printed the bare identifier.
    # ⭐ `pair_bootstrap_failed` IS THE ONE WORTH THE MOST HERE: the device DID
    # pair, the machine just did not get its token, and entering the same code
    # again finishes the job. Read as a bare code it looks like a dead end, so
    # somebody would have gone looking for a fresh code they do not need.
    # ⭐ THE RECOVERABLE ONE, WITH ITS DEADLINE. The committed branch stamps a
    # five-minute TTL on the half-paired document, so "the same code again" is
    # true only inside that window — after it the document is gone and the same
    # code answers `code_not_found`, contradicting the promise.
    "pair_bootstrap_failed": "It paired, but the computer didn’t finish picking "
                             "up its token — send me the same code again in the "
                             "next few minutes and it will resume. After that, "
                             "run “superresearch --pair” on the machine.",
    # ⛔ RESETTING THE CODE CANNOT RESTORE THE MISSING FIELD — only the pairing
    # handshake writes it, so a fresh code throws this again, indefinitely.
    "device_secret_missing": "That machine didn’t finish its side of the handshake — "
                             "run “superresearch --pair” on it again.",
    "unauthorized": "Your sign-in has expired — sign in again and send me the code.",
    "invalid_json": "That request didn’t reach the app in one piece — send me the "
                    "code again.",
    "internal_error": "Something went wrong at our end — nothing was paired; try again.",
}

# Friendly wording for the web app's UNPAIR-SELF route — the codes
# `device-remove` can receive. All nine are worded, including the two the agent
# cannot itself reach (`auth_delete_failed` is on the retire branch, which is
# gated on the machine's own synthetic login; `deviceId_mismatch` needs a token
# carrying a `deviceId` claim, which a person's session never has). They are
# covered anyway because the guard pins this table to the ROUTE, and a table
# with hand-maintained exclusions is how the last one came to share nothing
# with the route it was serving.
_UNLINK_ERRORS = {
    # ⛔⛔ IT DOES NOT SAY "NOTHING CHANGED", AND IT USED TO. The route deletes the
    # device's pending customToken BEFORE it attempts the rotation, and only then
    # returns this — so an unlink that stops here has already destroyed a handoff.
    # The true and useful claim is narrower: the machine is STILL YOURS.
    "rotation_failed": "Couldn’t unlink it — its access code wouldn’t change, and "
                       "unlinking without a fresh code would leave the computer "
                       "claimable by anyone holding the old one. It is still "
                       "linked to you; try again in a moment.",
    "not_authorized": "That computer isn’t linked to your account, so there’s "
                      "nothing to unlink.",
    "device_not_found": "That computer no longer exists — nothing to unlink.",
    "rate_limited": "",
    "unauthorized": "Your sign-in was refused — sign in again and ask me once more.",
    # ⛔ NOT "you named no computer" — the bridge refuses an empty id itself, so
    # the only way this code arrives is an id the app rejected as malformed.
    "deviceId_missing": "The app didn’t recognise that computer’s id. Ask me to list "
                        "them and name the one to remove.",
    "deviceId_mismatch": "That request named two different computers — ask me to "
                         "list them and name the one to remove.",
    "auth_delete_failed": "Couldn’t finish retiring that computer — nothing was "
                          "changed, so it is safe to try again.",
    "internal_error": "Something went wrong at our end — nothing changed; try again.",
}


def cmd_device_add(args) -> int:
    """Pair a device to this account by the code shown on its screen."""
    code, body = _post("/device/pair", {"code": args.code})
    if code != 200:
        err = body.get("error", "")
        msg = _device_refusal_line(err, _PAIR_ERRORS, "add the device",
                                   body.get("retryAfterMs"))
        return _emit(body, args.json, [f"✗ {msg}"], _fail_code(code))
    action = body.get("action")
    name = body.get("deviceName") or "the new device"
    if action in ("already-owner", "already-shared"):
        return _emit(body, args.json, [f"“{name}” is already on your account."])
    kind = "yours" if action in ("initial-pair", "re-pair") else "shared with you"
    if body.get("selected"):
        lines = [f"✓ Added “{name}” — it’s {kind} and selected."]
        lines.append("You can start researching whenever you like.")
    else:
        lines = [f"✓ Added “{name}” — it’s {kind} now."]
    # ⛔ THE DEVICE LIST'S OWN TAIL, NOT THE ONE IT RETIRED. "You can add, remove,
    # or switch devices anytime" names no route for adding — the devices screen
    # dropped it for that reason and this reply kept it (2026-09-24).
    lines.append("You can remove or switch computers anytime — just ask.")
    return _emit(body, args.json, lines)


def cmd_device_remove(args) -> int:
    """Unlink a device (owner: device stays installed, NEW code issued; sharer: leaves)."""
    dev, fail = _resolve_device_arg(args.device)
    if dev is None:
        return _emit({}, args.json, fail, 1)
    # ⛔ 50s, NOT THE DEFAULT 30. The bridge waits up to 35 on this route (it can
    # use its whole 30s budget) plus a 10s token refresh; a client that gave up
    # first would report a bridge that is not running and lose the new access code.
    code, body = _post("/device/remove", {"deviceId": dev.get("id")}, timeout=50)
    if code != 200:
        err = body.get("error", "")
        msg = _device_refusal_line(err, _UNLINK_ERRORS, "remove the device",
                                   body.get("retryAfterMs"))
        return _emit(body, args.json, [f"✗ {msg}"], _fail_code(code))
    label = _dev_label(dev)
    if body.get("action") == "left-shared":
        # ⛔ NO CODE HERE, ON PURPOSE. A sharer walking away is not handed the
        # key to the machine they just left — the route omits it and this says
        # nothing about it either, because mentioning a rotation they cannot use
        # only invites them to go looking for the new one.
        return _emit(body, args.json, [f"✓ Left the shared device “{label}”."])
    return _emit(body, args.json, [
        f"✓ Unlinked “{label}” from your account.",
        *_unlink_code_lines(body.get("pairCode")),
    ])


# ⛔⛔ THIS REPLACES A SENTENCE THAT WAS FALSE IN BOTH HALVES — the old copy
# promised nothing had gone and told the person to carry on using the code they
# already had. The first promise is true. The second was not: since 7.7A an
# owner-unlink ROTATES the code before it clears the owner, and it has to,
# because the claim route hands OWNERSHIP to whoever presents a code against an
# ownerless device and unlinking creates exactly that state. So the code they
# were told to keep stopped working as they read the sentence, and the live one
# sat on the machine's screen where nothing told them to look.
#
# ⛔ AND IT IS PRESENTED AS A CREDENTIAL, which is the other thing the product
# got wrong: SKILL.md called the code "NOT a password". On a machine with no
# owner it is stronger than one — it hands over the machine. The existing
# precedent ("An access code still lets someone in without asking you") understates
# it for exactly this moment, so this says the harder thing.
#
# ⛔ THE EXPLANATION LIVES IN A `#` COMMENT, NOT A DOCSTRING, and that is not
# style. The guard that keeps the false sentence out sweeps CODE ONLY —
# `code_only` blanks `#` comments and a docstring is a string literal, so a
# docstring quoting the old wording satisfies the search and the sweep goes
# green over a lie. It caught this file doing exactly that while being written.
def _unlink_code_lines(new_code: str | None) -> list[str]:
    """What an owner is told about the code after unlinking their own machine.

    ⛔⛔ THE FALLBACK USED TO SEND PEOPLE TO THE MACHINE'S SCREEN AND THAT WAS
    FALSE — cross-verify caught it, three lines from the field I had been reading.
    `unpair-self/route.ts` says it in its own words: "This is the only copy that
    exists: the machine cannot show it either, since the backend only ever learns
    a code from the pairing response and cannot read the admin-only entry it now
    lives in." The ex-owner cannot use the reveal either, because the rotation has
    already taken their ownership away. So there is no lookup to point at, and
    inventing one sent somebody to read a dead code off a screen.

    ⭐ WHAT IS TRUE IS THE UNCOMFORTABLE THING, so it is what this says: the code
    is gone, and the way back is to pair the machine again from the machine, which
    joins it as a NEW computer (`research.py`: "--pair does not restore anything —
    it mints a NEW deviceId").
    """
    if not new_code:
        return ["The device keeps running, but its access code changed and the new "
                "one did not reach me.",
                "That code cannot be looked up anywhere — this reply was the only "
                "copy. To use the computer again, run “superresearch --pair” on "
                "the machine itself; it will join as a new computer."]
    return [
        "The device keeps running, and its access code changed — the old one no "
        "longer works.",
        f"New access code: {new_code}",
        "Anyone who has that code can claim this computer as its owner, so keep "
        "it like a password.",
    ]


# ⛔⛔ ITS OWN TABLE, NOT `_PAIR_ERRORS`. Three codes appear in both and mean
# different things on the two routes. Pairing's `revoked_sharer` ends "ask them to
# share it again" — on the ask route that is precisely what is being refused, so
# borrowing it would invite the retry that just failed; its `rate_limited` says
# "wait a few minutes" against a per-HOUR ceiling; and its `share_cap_reached`
# describes a pairing rather than a queue. The same words in two places would have
# been the shortcut and wrong in all three.
#
# ⭐ THE SAME CLAIMS AS THE TERMINAL'S `_ASK_FAILURES`, in this client's voice. A
# guard compares what the two say, not how they say it — cli.py has no curly
# apostrophes and this file is full of them.
_ASK_ERRORS = {
    "device_not_found": "That computer isn’t offered publicly any more — its owner "
                        "may have made it private, or the id may be wrong.",
    "is_owner": "That one is already yours.",
    "already_shared": "You can already use that computer.",
    "revoked_sharer": "Its owner removed your access to that computer before, so "
                      "this isn’t something asking again can change.",
    "share_cap_reached": "That computer is already shared with as many people as "
                         "it can hold.",
    "already_pending": "You’ve already asked for that one — it’s waiting on its owner.",
    "recently_denied": "Its owner said no recently. Asking again is refused for a "
                       "week from the day they answered.",
    "too_many_requests": "You have as many requests waiting as an account can have "
                         "— one has to be answered or expire first.",
    "device_queue_full": "That computer already has as many people waiting as it "
                         "can queue.",
    "invalid_json": "That request didn’t reach the app in a form it could read.",
    "device_id_required": "That isn’t an id any computer could have.",
    "unauthorized": "This agent’s sign-in was refused — sign in again and I’ll retry.",
    # ⛔ THE ROUTE'S OWN CATCH-ALL, missing from both tables in the first pass, so
    # its word reached the person as the sentence.
    "internal_error": "The app hit a problem of its own answering that. Nothing was "
                      "sent, so it’s safe to try again.",
}

# ⛔⛔ THE TWO LIST ROUTES HAD NO TABLE AT ALL, so `rate_limited`, `unauthorized`
# and `internal_error` reached the person as machine tokens — on the two screens
# of a wave whose stated purpose was to stop that. Browse allows thirty looks
# every five minutes and every chat ask spends one, so it is genuinely reachable.
_LIST_ERRORS = {
    "unauthorized": "This agent’s sign-in was refused — sign in again and I’ll retry.",
    "internal_error": "The app hit a problem of its own answering that. Nothing "
                      "about your account changed.",
}


# ⛔ ONE ROW PER CALLER PHRASE, AND A GUARD PINS THAT EVERY CALLER HAS ONE. A
# phrase with no row keeps its past tense and ships "Couldn't asked for ...", which
# is how the second caller shipped broken English for two waves.
_PLAIN_VERBS = {
    "looked for public computers": "look for public computers",
    "asked for your requests": "ask for your requests",
}


def _plain_verb(what: str) -> str:
    return _PLAIN_VERBS.get(what, what)


def _device_refusal_line(err, table: dict, what: str, retry_after_ms=None) -> str:
    """The chat sentence for one refusal from the pair or unlink route.

    ⛔⛔ THE TWO DEVICE ROUTES WERE THE ONLY REFUSAL PATHS IN THIS FILE WITH NO
    HELPER, and cross-verify found both holes the helper exists to close. A bare
    `table.get(err, fallback)` meant a SIGNED-OUT caller read the bridge's own
    words — "not signed in — run /login" — which hands a chat user the terminal's
    command; and a synthesised `http_500` (a Firestore outage inside the route's
    rate limiter, which sits outside its try) printed that identifier verbatim,
    the exact thing this wave was written to remove. Every sibling route already
    had this shape.

    ⛔ AND THE WAIT IS THE SERVER'S NUMBER OR NOTHING. Both routes send
    `retryAfterMs` and the bridge relays it; the chat client read it on four
    other routes and not on these two, so it invented "a few minutes" beside a
    number it had been handed — while the terminal said "about 5 minutes" for the
    same reply. The two clients disagreed about the same 429.
    """
    if err == "rate_limited":
        ms = retry_after_ms
        ok = (not isinstance(ms, bool)) and isinstance(ms, (int, float)) and ms > 0
        if not ok:
            return f"Too many attempts to {what} in a row — give it a minute."
        mins = max(1, int((ms + 59_999) // 60_000))
        return (f"Too many attempts to {what} in a row — try again in about "
                f"{mins} minute{'' if mins == 1 else 's'}.")
    said = table.get(err)
    if said:
        return said
    if str(err).lower().startswith("not signed in"):
        return _signed_out_or(err)
    if str(err).startswith("http_"):
        return f"The app answered that with nothing I can read (HTTP {str(err)[5:]})."
    return f"couldn’t {what}: {err or 'no reason given'}"


def _signed_out_or(err) -> str:
    """The chat sentence for a signed-out refusal; anything else unchanged.

    ⛔ THE BRIDGE ANSWERS 401 WITH A SENTENCE, NOT A TOKEN — "not signed in — run
    /login" — and `/login` belongs to the terminal. In chat the person says it in
    words, so relaying the bridge's text hands them a command that does nothing.
    """
    if str(err).lower().startswith("not signed in"):
        return "You’re not signed in yet — tell me to log you in and I’ll send a link."
    return str(err)


def _list_refusal_line(what: str, err: str, retry_after_ms=None) -> str:
    """The sentence for one refusal from a list route, with its own wait."""
    if err == "rate_limited":
        ms = retry_after_ms
        ok = (not isinstance(ms, bool)) and isinstance(ms, (int, float)) and ms > 0
        if not ok:
            return f"You’ve {what} too many times in a row — give it a minute."
        mins = max(1, int((ms + 59_999) // 60_000))
        return (f"You’ve {what} too many times in a row — try again in about "
                f"{mins} minute{'' if mins == 1 else 's'}.")
    said = _LIST_ERRORS.get(err)
    if said:
        return said
    # ⛔⛔ THE BRIDGE'S OWN 401 IS A SENTENCE, NOT A TOKEN. `_LIST_ERRORS` keys on
    # the web app's words ("unauthorized"), but a signed-OUT caller never reaches
    # the web app — the bridge answers first with "not signed in — run /login",
    # which matched no row and fell through to the fallback below. The people that
    # hits are exactly the ones this wave is for: no computer, and not signed in.
    # ⛔ And it must NOT print the bridge's own text: "/login" is the terminal's
    # command and this is chat, where the person says it in words.
    if str(err).lower().startswith("not signed in"):
        return _signed_out_or(err)
    if str(err).startswith("http_"):
        return f"The app answered that with nothing I can read (HTTP {str(err)[5:]})."
    # ⛔⛔ `what` IS A PAST-TENSE PHRASE — it has to be, for the rate-limit
    # sentence above ("You've asked for your requests too many times"). This line
    # needs the plain verb, and it patched exactly ONE word of one caller's
    # phrase: "looked" → "look". The other caller says "asked", so its refusal
    # read "Couldn't asked for your requests: ...". The table converts every verb
    # this helper is called with, and an unconverted one is caught by a guard
    # rather than shipped as broken English.
    return f"Couldn’t {_plain_verb(what)}: {err or 'no reason given'}"


def _ask_refusal_line(err: str, retry_after_ms=None) -> str:
    """The sentence for one ask refusal, with a wait only when the reply gave one.

    ⛔ THE WAIT IS THE SERVER'S NUMBER OR NOTHING — inventing one beside a number
    that was handed over is the worse half of both habits.
    ⛔ AND THE CLAIM THAT USED TO STAND HERE WAS FALSE: it called this "the first
    refusal in the product where the reply carries `retryAfterMs`". The pair and
    unlink routes both send it, two hundred lines above, and until 7.9-5's
    cross-verify round both of those invented "a few minutes" instead of reading
    it. A comment asserting it is the only one of its kind is how the other two
    stayed unnoticed.
    """
    if err == "rate_limited":
        ms = retry_after_ms
        ok = (not isinstance(ms, bool)) and isinstance(ms, (int, float)) and ms > 0
        if not ok:
            return ("You’ve asked for as many computers as an account may in one "
                    "hour.")
        mins = max(1, int((ms + 59_999) // 60_000))
        return (f"You’ve asked for as many computers as an account may in one hour "
                f"— the next one can go in about {mins} minute"
                f"{'' if mins == 1 else 's'}.")
    said = _ASK_ERRORS.get(err)
    if said:
        return said
    # ⛔ The bridge hands over a STATUS for anything it cannot word; the client
    # writes the sentence, so the two do not both write it.
    if str(err).startswith("http_"):
        return (f"The app answered that with nothing I can read (HTTP {str(err)[5:]}) "
                f"— nothing was sent.")
    return f"Couldn’t ask for that computer: {err or 'no reason given'}"


def _public_rows_block(rows: "list[dict]") -> "list[str]":
    """Every public row, with the id shown ONLY on the ones that need it.

    ⭐ A ROW NEEDS ITS ID WHEN ANOTHER ROW READS THE SAME. That question cannot be
    answered one row at a time, which is why it lives here and not in the
    renderer. Both screens — the browse list and the no-computer empty state —
    go through this, so they cannot drift into two different answers about when
    an id appears.
    """
    seen: "dict[str, int]" = {}
    for d in rows:
        label = str(d.get("label") or "").strip() or "(unnamed)"
        seen[label] = seen.get(label, 0) + 1
    out = []
    for d in rows:
        label = str(d.get("label") or "").strip() or "(unnamed)"
        out.append(_public_row_line(d, show_id=seen.get(label, 0) > 1))
    return out


def _public_row_line(d: dict, show_id: bool = False) -> str:
    """ONE public row, in this client's voice — used by the browse list AND by the
    empty state, so the two screens cannot drift apart.

    ⛔⛔ EXTRACTING THIS DOES NOT TEST IT. Both consumers are pinned separately;
    a guard that only drove the browse list would let the empty state grow its
    own second phrasing, which is the exact way the seven deviceless sentences
    this wave is unifying came to exist in the first place.
    """
    label = str(d.get("label") or "").strip() or "(unnamed)"
    dot = " · online" if d.get("online") else " · offline"
    # ⛔⛔ `full` IS A REFUSAL IN ADVANCE, not a label. The ask route answers
    # `share_cap_reached` for these with certainty, and a quiet word beside
    # an invitation spent one of five hourly asks on a guaranteed no.
    full = " · can’t take anyone else" if d.get("full") else ""
    # ⛔⛔ THE ID IS NOT DECORATION, BUT IT IS ALSO NOT ALWAYS NEEDED. Public
    # labels genuinely collide — every unnamed machine is the identical string
    # "Research computer" — and the list is ordered online-first over a
    # thirty-second window, so when two rows read the same neither the name nor
    # the position identifies one. There the id is the only handle and the ask
    # takes it.
    # ⭐ BUT PRINTING IT ON EVERY ROW COST MORE THAN IT BOUGHT (owner, 2026-09-19):
    # a 32-character hex string beside a one-word name is the widest thing on the
    # screen and reads as something the person has to deal with. So the CALLER
    # decides — it can see the whole list, which is the only place the question
    # "do two of these read the same?" can actually be answered.
    return f"  • {label}{dot}{full}" + (f"  (id {d.get('deviceId')})" if show_id else "")


def cmd_devices_public(args) -> int:
    """The computers other people are offering publicly."""
    code, body = _get("/devices/public", timeout=40)
    if code != 200:
        return _emit(body, args.json,
                     [f"✗ {_list_refusal_line('looked for public computers', body.get('error', ''), body.get('retryAfterMs'))}"],
                     _fail_code(code))
    # ⛔⛔ THE SAME GUARD THE EMPTY STATE GOT AND THIS SCREEN DID NOT. The bridge
    # validates that `devices` is a LIST and never that a row is a dict, and this
    # renderer calls `.get` on every row — so one bad row from the app takes the
    # browse command down while the empty state beside it survives.
    rows = [d for d in (body.get("devices") or []) if isinstance(d, dict)]
    if not rows:
        lines = ["Nobody is offering a computer publicly right now.",
                 _PUBLIC_NONE_WHY]
        # ⛔⛔ THE EMPTY BRANCH IS WHERE TRUNCATION MATTERS MOST and it was
        # reported only on the other one. `truncated` is computed on the raw scan,
        # so zero rows can mean "the scan filled up and everything in it was
        # filtered" — over which a flat "nobody is offering" is the one reading
        # that is definitely wrong.
        if body.get("truncated"):
            lines.append(_PUBLIC_TRUNCATED_NONE)
        return _emit(body, args.json, lines)
    lines = [f"{_PUBLIC_HEAD} ({len(rows)}):"]
    lines += _public_rows_block(rows)
    if body.get("truncated"):
        # ⛔ ABOUT THE SCAN, NOT ABOUT THIS LIST. The flag is set before the app
        # drops the ones you cannot ask for, so it can be true beside a short
        # list, and there is no next page to fetch.
        lines.append(_PUBLIC_TRUNCATED_SOME)
    # ⛔⛔ "YOUR NAME AND EMAIL ADDRESS" IS WRONG TWICE AND IT WAS FIXED IN ONE
    # PLACE ONLY. The consent question was corrected in 7.9-2 — the owner sees
    # the NAME, and the email only when no name is set — and a sibling test
    # forbids the old phrasing there by name. This trailer, on the screen that
    # decides whether to ask at all, kept saying it. Same claim, same words, both
    # screens.
    lines.append(_PUBLIC_ASK_INVITE)
    return _emit(body, args.json, lines)


def cmd_device_ask(args) -> int:
    """Ask the owner of a public computer for access to it."""
    wanted = (getattr(args, "device", "") or "").strip()
    if not wanted:
        return _emit({}, args.json,
                     ["Which computer? Ask me for the public list and name one of "
                      "those."], 1)
    # ⛔⛔ AN ID GOES STRAIGHT TO THE ROUTE. Resolving everything through the
    # browse list first was wrong twice over, and cross-verify found both: the
    # projection DROPS machines this account is already on, so after an approval
    # the person who was just granted a computer was told no such public computer
    # exists; and it drops the caller's own and the private ones too, so
    # `is_owner`, `already_shared` and `revoked_sharer` — three of the sentences
    # written for this verb — could never be reached from chat at all. The route
    # is the thing that knows; the list is only for turning a NAME into an id.
    label = wanted
    if _looks_like_a_device_id(wanted):
        device_id = wanted
    else:
        dev, fail = _resolve_public_device(wanted)
        if dev is None:
            return _emit({}, args.json, fail, 1)
        device_id = dev.get("deviceId")
        label = str(dev.get("label") or "").strip() or wanted
        # ⛔ A FULL MACHINE IS A CERTAIN NO, and asking spends one of five an
        # hour. The projection already published the bit; spending the ask to be
        # told what the row said is the shape this wave exists to remove.
        if dev.get("full"):
            return _emit({}, args.json, [
                f"“{label}” is already shared with as many people as it can hold, "
                f"so a request would be refused.",
            ], 1)
    # ⭐ THE CHAT THAT IS WAITING GOES WITH THE ASK. The approval lands in a
    # collection no credential here can read, so the bridge has to knock on the
    # web route to notice it — and it only knows to knock, and where to deliver
    # the answer, because this request said which chat asked. Without it the
    # owner says yes and nobody is told (owner, 2026-09-20).
    ask_payload = {"deviceId": device_id}
    _ask_origin = _origin_from_env()
    if _ask_origin:
        ask_payload["origin"] = _ask_origin
    code, body = _post("/device/ask", ask_payload)
    if code != 200:
        return _emit(body, args.json,
                     [f"✗ {_ask_refusal_line(body.get('error', ''), body.get('retryAfterMs'))}"],
                     _fail_code(code))
    return _emit(body, args.json, [
        f"✓ Asked for “{label}”. Its owner decides — nothing runs on it until they "
        f"say yes.",
        "They see your name — or your email, if you haven’t set one.",
        "Ask me any time what you’re waiting on.",
    ])


# ⛔⛔ ANSWERING A REQUEST HAS ITS OWN TABLE. Five codes appear on both this
# route and the ask route and mean DIFFERENT things on each: `device_not_found`
# there means "not offered publicly", here it means "not yours any more";
# `is_owner` there means "already yours", here it means the person asking owns
# it; `revoked_sharer` there is about the caller and here it is about somebody
# else. Borrowing `_ASK_ERRORS` would say the wrong true thing.
# ⭐ THE SAME CLAIMS AS THE TERMINAL'S `_DECIDE_FAILURES`, worded for chat. A
# guard compares what the two say, not how they say it.
_DECIDE_ERRORS = {
    "device_not_found": "That computer isn’t yours any more.",
    "request_not_found":
        "There’s no request from that person for that computer — it may have "
        "been answered already, or it may have run out.",
    "request_mismatch":
        "That request doesn’t belong to that computer. Ask me for the queue "
        "again and answer from what it shows.",
    # ⛔⛔ THREE STATES BEHIND ONE CODE — see the terminal's note.
    "request_not_pending":
        "That request isn’t open any more — it was already answered, or it ran "
        "out. Ask me for the queue again to see what is still waiting.",
    "is_owner": "That person owns that computer, so there’s nothing to answer.",
    "revoked_sharer":
        "You removed this person from that computer before. Resetting its access "
        "code is what lets them back in.",
    "share_cap_reached":
        "That computer is already shared with as many people as it can hold. "
        "Remove someone first.",
    "invalid_json": "That answer didn’t reach the app in a form it could read.",
    "device_id_required": "That isn’t an id any computer could have.",
    "requester_required": "That isn’t the id of a person who could have asked.",
    "decision_required":
        "The app didn’t get a yes or a no, so nothing was answered.",
    # ⛔ NO RETRY PROMISE. The ask table's row for this same code ends "and I'll
    # retry", and nothing here retries anything — one code should not make two
    # different promises inside one client.
    "unauthorized": "This agent’s sign-in was refused — sign in again.",
    "internal_error":
        "The app hit a problem of its own answering that. Nothing about that "
        "request changed, so it’s safe to try again.",
}


def _decide_refusal_line(err: str, retry_after_ms=None) -> str:
    """One refusal from the answer-a-request route, in words.

    Same ladder as the ask: the server's own wait first, then the table, then an
    unreadable reply, then the code rather than silence. ⛔ The bridge's OWN
    refusals — an id this account cannot reach, a machine somebody else owns —
    are whole sentences already and fall through to the last tier on purpose.
    """
    if err == "rate_limited":
        mins = None
        if isinstance(retry_after_ms, (int, float)) and not isinstance(
                retry_after_ms, bool) and retry_after_ms > 0:
            mins = max(1, int((retry_after_ms + 59_999) // 60_000))
        if mins is None:
            return ("The app is rate-limiting answers from this account just now. "
                    "Nothing was answered.")
        return (f"The app is rate-limiting answers from this account. Try again in "
                f"about {mins} minute{'s' if mins != 1 else ''}.")
    said = _DECIDE_ERRORS.get(err)
    if said is not None:
        return said
    if str(err).startswith("http_"):
        return (f"The app answered that with nothing I can read (HTTP {err[5:]}) "
                f"— nothing was answered.")
    return f"Couldn’t answer that request: {err or 'no reason given'}"


def _incoming_or_lines() -> "tuple[list, list, int]":
    """The people waiting on this account's machines — or the lines saying why
    there are none, and the exit code that failure deserves.

    ⛔ THE CODE COMES BACK TOO. Returning only lines made the caller exit 1 for
    everything, so an unreachable bridge — which every sibling reports as 2 —
    was reported as a refusal the person could act on.
    """
    code, body = _get("/devices/requests", timeout=40)
    if code != 200:
        return [], [f"✗ {_list_refusal_line('asked for your requests', body.get('error', ''), body.get('retryAfterMs'))}"], _fail_code(code)
    rows = body.get("incoming") or []
    if not rows:
        return [], ["Nobody is waiting on your computers."], 1
    return rows, [], 0


def _describe_incoming(rows: list, whole: bool = True) -> list:
    """The queue, as lines. ⛔ THE PERSON'S NAME IS A SNAPSHOT taken the day they
    asked and falls back to a neutral word shared by everybody the app could not
    look up, so the machine is named on every row too — a row that says only who
    is asking is unanswerable when two people are waiting."""
    # ⛔ THE HEADER COUNTS WHAT IT IS SHOWING, and `whole` says whether that is
    # the queue. Called with a filtered subset it printed "People asking to use
    # your computers (2)" over two of five — a false count under a header that
    # claims to be everybody.
    lines = [f"People asking to use your computers ({len(rows)}):" if whole
             else f"Matching ({len(rows)}):"]
    for d in rows:
        who = str(d.get("requesterLabel") or "").strip() or "Someone"
        what = str(d.get("deviceLabel") or "").strip() or "(unnamed)"
        lines.append(f"  • {who} wants “{what}”")
    return lines


def _resolve_asker(who: str, rows: list) -> "tuple[dict | None, list]":
    """One waiting person, from what somebody typed.

    ⛔⛔ EXACT FIRST, THEN ONE UNIQUE SUBSTRING, THEN NOTHING — the same ladder
    `_resolve_device_arg` uses for machines, for the same reason: a wrong match
    here does not misname a thing, it lets a stranger onto somebody's computer.
    An ambiguous or absent match prints the queue instead of guessing, and the
    reply names in full whoever was actually answered.
    """
    bare = (who or "").strip().strip(_NL_QUOTE_CHARS).strip()
    if not bare:
        if len(rows) == 1:
            return rows[0], []
        return None, (["Which one?"] + _describe_incoming(rows) +
                      ["Say for example: approve " +
                       (str(rows[0].get("requesterLabel") or "").strip()
                        or "the first one")])
    low = bare.lower()
    # ⛔⛔ THE EXACT RUNG NEEDS THE UNIQUENESS TEST TOO, and it did not have one
    # while the substring rung below carefully did. The queue holds one row per
    # MACHINE per person, so somebody who asked for two of this account's
    # computers is two rows with the identical label AND the identical id — and
    # "approve Alex" silently answered the older one. Two askers with no display
    # name are both the neutral fallback word, so "approve Someone" did the
    # same. This function's own docstring promised the opposite.
    exact = [d for d in rows
             if str(d.get("requesterUid") or "") == bare
             or str(d.get("requesterLabel") or "").strip().lower() == low]
    if len(exact) == 1:
        return exact[0], []
    if len(exact) > 1:
        return None, (["That matches more than one thing they are waiting on."] +
                      _describe_incoming(exact, whole=False) +
                      ["Answer one at a time from a terminal, where each row "
                       "carries both ids: `agent device requests`."])
    hits = [d for d in rows
            if low in str(d.get("requesterLabel") or "").strip().lower()]
    if len(hits) == 1:
        return hits[0], []
    if len(hits) > 1:
        return None, (["More than one person waiting matches that."] +
                      _describe_incoming(hits, whole=False) +
                      ["Say the whole name. If two of them read the same, answer "
                       "from a terminal — `agent device requests` prints an id "
                       "on every row."])
    return None, ([f"Nobody called “{bare}” is waiting on your computers."] +
                  _describe_incoming(rows))


def _cmd_device_decide(args, decision: str) -> int:
    """Approve or deny one person waiting on one of this account's machines."""
    rows, lines, rc = _incoming_or_lines()
    if not rows:
        # ⛔ THE BRIDGE'S OWN CODE, NOT A FLAT 1. Every sibling exits 2 when the
        # bridge is unreachable and 1 when the answer was a refusal; this one
        # reported a refusal for both.
        return _emit({}, args.json, lines, rc)
    row, fail = _resolve_asker(getattr(args, "person", "") or "", rows)
    if row is None:
        return _emit({}, args.json, fail, 1)
    code, body = _post("/device/decide",
                       {"deviceId": row.get("deviceId"),
                        "requesterUid": row.get("requesterUid"),
                        "decision": decision}, timeout=40)
    if code != 200:
        return _emit(body, args.json,
                     [f"✗ {_decide_refusal_line(body.get('error', ''), body.get('retryAfterMs'))}"],
                     _fail_code(code))
    who = str(row.get("requesterLabel") or "").strip() or "They"
    name = body.get("deviceName") or str(row.get("deviceLabel") or "").strip() \
        or "that computer"
    if body.get("decision") == "approved":
        # ⛔⛔ A STATE, NEVER AN EVENT. The route closes an already-shared request
        # as approved and writes nothing to the machine, so "you have just added
        # them" is false on one of the two branches that reach here. "They can
        # use it" is true on both.
        return _emit(body, args.json, [
            f"✓ {who} can use “{name}”.",
            "It turns up on their side as one of their computers.",
        ])
    return _emit(body, args.json, [
        f"✓ Said no to {who} for “{name}”.",
        "They can’t ask again for a week. The app tries to tell them, but that "
        "depends on their own notification settings. Giving them the access code "
        "still works if you change your mind.",
    ])


def cmd_device_approve(args) -> int:
    return _cmd_device_decide(args, "approve")


def cmd_device_deny(args) -> int:
    return _cmd_device_decide(args, "deny")


def cmd_device_visibility(args) -> int:
    """Set who can FIND one of this account's machines."""
    value = (getattr(args, "value", "") or "").strip().lower()
    if value not in ("public", "private"):
        return _emit({}, args.json, ["Say public or private."], 1)
    hint = (getattr(args, "device", "") or "").strip()
    if hint:
        dev, fail = _resolve_device_arg(hint)
        if dev is None:
            return _emit({}, args.json, fail, 1)
    else:
        dev, fail = _pick_owned_device()
        if dev is None:
            return _emit({}, args.json, fail, 1)
    code, body = _post("/device/visibility",
                       {"deviceId": dev.get("id"), "visibility": value}, timeout=40)
    if code != 200:
        # ⛔⛔ NOT `_list_refusal_line` — see the terminal's note. Its "Couldn’t
        # …" prefix contradicts the very payload the bridge built to say the
        # write may have landed.
        said = body.get("error") or "the app gave no reason"
        return _emit(body, args.json, [f"✗ {said}"], _fail_code(code))
    name = body.get("deviceName") or _dev_label(dev)
    state = body.get("visibility")
    head = (f"✓ “{name}” is now {state}." if body.get("changed")
            else f"✓ “{name}” is already {state}. Nothing to change.")
    if state == "public":
        lines = [head,
                 "Other people can find it and ask to use it. You still approve "
                 "every person yourself."]
        # ⛔⛔ THE PUBLISHED NAME IS THE DISCLOSURE, not decoration: a computer
        # nobody has renamed reports a hostname that often carries its owner's
        # own name, and this is where that becomes visible to strangers.
        if body.get("publicLabel"):
            lines.append(f"They see it as “{body.get('publicLabel')}”.")
    else:
        lines = [head,
                 "Nobody can find it. An access code still lets someone in without "
                 "asking you."]
    return _emit(body, args.json, lines)


def _pick_owned_device() -> "tuple[dict | None, list]":
    """The machine an owner verb should act on when nobody named one.

    ⛔ OWNED ONLY. A shared machine is somebody else's to publish, and offering
    one in this picker would send the person into a refusal the picker could
    have spared them — the same reasoning the terminal's send-logs advice uses.
    """
    code, body = _get("/devices")
    if code != 200:
        return None, [f"✗ {body.get('error', code)}"]
    owned = [d for d in (body.get("devices") or []) if d.get("owned")]
    if not owned:
        return None, ["None of the computers on this account are yours to change "
                      "— that setting belongs to whoever owns the machine."]
    if len(owned) == 1:
        return owned[0], []
    return None, (["Which computer?"] +
                  [f"  • {_dev_label(d)}" for d in owned] +
                  [f'Say for example: make “{_dev_label(owned[0])}” public.'])


def _looks_like_a_device_id(wanted: str) -> bool:
    """Is this an id rather than a name somebody typed?

    ⛔ A SEPARATOR AND SOME LENGTH, never a bare length test. The first version of
    the sibling check in `_nl_resolve` called any six-letter word an id, which is
    how "ask for feedback" reached a consent question about disclosing somebody's
    name. A device id has no spaces and carries a hyphen or an underscore; a
    machine somebody NAMED almost always has a space, or neither.

    ⛔⛔ AND THE SHAPE THE APP ACTUALLY MINTS HAS NO SEPARATOR AT ALL.
    `/api/devices/initiate-pair` writes `randomUUID().replace(/-/g, "")` — thirty-
    two lowercase hex characters — so every real id failed this, went to the browse
    list instead, and was looked up as a NAME. That list drops the caller's own
    machines, the ones they already share and the private ones, which is precisely
    why the id route exists; so pasting a real id out of a browse listing reached
    "no public computer is called that" about a computer that was right there.

    ⭐ THE SEPARATOR RULE IS KEPT FOR EVERYTHING ELSE — it is what holds "feedback"
    out — and the minted shape is admitted beside it. Thirty-two hex characters is
    not a name anybody types.
    """
    w = (wanted or "").strip()
    if " " in w:
        return False
    if re.fullmatch(r"[0-9a-fA-F]{32}", w):
        return True
    if len(w) < 8:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*[-_][A-Za-z0-9_-]*[A-Za-z0-9]", w))


# ⛔⛔⛔ A SENTENCE FRAGMENT IS NOT A MACHINE NAME, AND CROSS-VERIFY FOUND THIS
# WAVE MINTING THEM. The capture arms take whatever sits between a verb and a
# polarity word, and ordinary English put these into a lookup that HIDES with no
# confirm:
#     `why is my mac not public`        -> “mac not”  -> hid “Mac Notebook”
#     `make sure my mac is not public`  -> “sure my mac is” -> offered to PUBLISH
#     `my mac should not be public`     -> “should not be”  -> refused
#     `add my computer to the public list` -> “to the”
# ⭐ THE TEST IS THE LAST WORD. A machine name ends in a machine noun, an
# identifier, or a word somebody chose; it never ends in a copula, a modal, a
# negator, a preposition or a determiner. Applied after every trim, so it judges
# what the command is actually about to act on.
_NOT_A_NAME_TAIL = (r"(?:is|are|was|were|be|been|being|am|isn'?t|aren'?t|wasn'?t|"
                    r"weren'?t|has|have|had|do|does|did|doesn'?t|don'?t|didn'?t|"
                    r"should|shouldn'?t|would|wouldn'?t|will|won'?t|can|can'?t|"
                    r"could|couldn'?t|may|might|must|mustn'?t|shall|need|needs|"
                    r"want|wants|keep|keeps|stay|stays|remain|remains|get|gets|"
                    r"not|never|no|nor|and|or|but|if|so|to|of|in|on|at|by|for|"
                    r"from|with|into|onto|about|the|a|an|my|our|your|their|its|"
                    r"his|her|that|this|these|those|it|them|me|us|you|i|we|they)")


def _names_a_machine(span: str) -> bool:
    """Could this captured span be a machine somebody named?

    ⛔ It is a test on the LAST WORD, not on the whole span, because a real name
    can contain any of these words — “Now or Never Mac”, “Show and Tell PC”,
    “Not My Mac” — and only the ending tells you whether the capture stopped
    where a name stops or where a clause does.
    """
    w = (span or "").strip().strip(_NL_QUOTE_CHARS).strip()
    if not w:
        return False
    return not re.search(rf"(?:^|\s){_NOT_A_NAME_TAIL}$", w, re.I)


def _looks_like_a_machine_token(word: str) -> bool:
    """Is this bare word a machine somebody would type without a noun in front?

    ⛔⛔ WAVE 1.2 MEASURED 432 DEAD PHRASINGS IN THIS ONE SHAPE — more than a
    third of everything the capture corpus killed. `hide LABPC001`,
    `make LABPC001 public` and `remove LABPC001` all reached the catch-all,
    because hide, publish and unlink each require a machine NOUN in the message
    and a bare id carries none. `switch to LABPC001` worked, so the person had no
    way of knowing which verbs would take it.

    ⛔ `_looks_like_a_device_id` CANNOT ANSWER THIS. It demands a hyphen or an
    underscore, which is right for an id the app minted and wrong for a hostname
    a person reads off a screen: LABPC001 has neither. This is the weaker test —
    a digit or a separator, no spaces, and never a bare number, which would make
    `hide 2024` name a machine.
    """
    w = (word or "").strip().strip(_NL_QUOTE_CHARS)
    if " " in w or len(w) < 5 or w.isdigit():
        return False
    return bool(re.search(r"\d", w) or re.search(r"[-_]", w)) and \
        bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", w))


def _resolve_public_device(wanted: str):
    """Turn what the person said into one public row, or the lines to say instead.

    ⛔⛔ AN EXACT ID WINS OUTRIGHT AND IS CHECKED FIRST, because it is the only
    thing on the row that is unique. Labels are not: an unnamed machine's public
    label is the literal string "Research computer" for everybody, so a name match
    over a list of them is a coin flip, and this refuses rather than tossing it.
    """
    code, body = _get("/devices/public", timeout=40)
    if code != 200:
        # ⛔ THE LIST'S OWN TABLE HERE TOO. This lookup is a browse call made on
        # the way to an ask, so its refusals are the browse route's — and relaying
        # the raw code was the same defect one function along.
        return None, [f"✗ {_list_refusal_line('looked for public computers', body.get('error', ''), body.get('retryAfterMs'))}"]
    rows = [d for d in (body.get("devices") or []) if isinstance(d, dict)]
    if not rows:
        return None, ["Nobody is offering a computer publicly right now, so there’s "
                      "nothing to ask for yet."]
    # ⛔ STRIPPED ONCE, BEFORE BOTH COMPARISONS, AND ALL SIX MARKS. The first
    # version compared the id against the RAW argument and stripped only four of
    # the six characters this file itself enumerates, so a quoted id matched
    # nothing and a curly-single-quoted name matched nothing either.
    bare = (wanted or "").strip().strip(_NL_QUOTE_CHARS).strip()
    for d in rows:
        if str(d.get("deviceId") or "") == bare:
            return d, []
    low = bare.lower()
    hits = [d for d in rows if str(d.get("label") or "").strip().lower() == low]
    if len(hits) == 1:
        return hits[0], []
    if len(hits) > 1:
        return None, [
            f"More than one public computer is called “{bare}” — that name is the "
            f"default for a computer nobody has renamed.",
            "Give me its id instead; I print one beside every row.",
        ]
    return None, [f"No public computer is called “{bare}”.",
                  "If its owner just said yes, it is one of YOUR computers now — "
                  "ask me to list them.",
                  "Otherwise ask me for the public list and name one from it."]


def cmd_device_requests(args) -> int:
    """Both halves of the queue: people waiting on THIS account's machines, and
    what this account is waiting on from other people.

    ⛔ Printed apart and never summed. Only one half is anybody's to act on from
    here, and the other is somebody else's decision.
    """
    code, body = _get("/devices/requests", timeout=40)
    if code != 200:
        return _emit(body, args.json,
                     [f"✗ {_list_refusal_line('asked for your requests', body.get('error', ''), body.get('retryAfterMs'))}"],
                     _fail_code(code))
    rows = body.get("requests") or []
    incoming = body.get("incoming") or []
    # ⛔⛔ THE OWNER'S HALF LEADS, because it is the only one anybody can answer
    # from here. ⛔ AND ITS ABSENCE IS SAID OUT LOUD: silence about it reads as
    # "this screen does not cover that", which is exactly what it used to mean.
    if incoming:
        lines = _describe_incoming(incoming)
        # ⛔⛔ WHAT A YES MEANS AND WHAT A NO COSTS, BOTH BEFORE THE DECISION. The
        # web app puts the first beside its buttons and never states the second
        # to the owner at all — it tells the ASKER about the week and leaves the
        # person spending it uninformed.
        lines.append("Anyone you say yes to can run research on that computer — "
                     "the same as somebody you gave an access code to. Saying no "
                     "stops them asking again for a week; the app tries to tell "
                     "them, but that depends on their own notification settings.")
    else:
        lines = ["Nobody is waiting on your computers."]
    if not rows:
        lines.append("You’re not waiting on any computer.")
    else:
        lines.append(f"Waiting on ({len(rows)}):")
        for d in rows:
            label = str(d.get("deviceLabel") or "").strip() or "(unnamed)"
            lines.append(f"  • “{label}”  (id {d.get('deviceId')})")
    # ⛔⛔ ON BOTH BRANCHES. A row here means still waiting and nothing else; a row
    # that has GONE means answered — either way — or seven days passed, or that
    # computer changed hands or was retired. Nothing in the reply carries a status,
    # so calling a missing row a refusal would be inventing a fact.
    # ⛔⛔ THE FIRST VERSION PROMISED "ask again and I'll tell you which it was",
    # and that is false for the one answer people care about. An APPROVAL puts
    # this account on the machine, and the browse projection drops machines you
    # are already on — so asking again cannot report a yes; it answers "no public
    # computer is called that". A yes reports itself by the machine turning up in
    # your own list.
    # ⛔ THIS SENTENCE IS ABOUT THE ASKER'S HALF AND SAYS SO. It used to be the
    # only half on the screen, so "requests" needed no qualifier; with the
    # owner's queue above it, an unqualified "only unanswered requests show here"
    # would read as a claim about people waiting on YOU as well — and the two
    # halves lose a row for different reasons.
    lines.append("Of the ones you asked for, only unanswered requests show here. "
                 "Once one is answered it leaves this list whichever way it went. "
                 "A yes shows up as the computer appearing in your own list; for "
                 "a no, ask for it again and I’ll tell you.")
    return _emit(body, args.json, lines)


def _pick_device_lines(body: dict, reason: str, about: str = "this") -> list[str]:
    """Chat lines for the 'which computer should run this?' ask.

    The account normally HAS research computers and just needs to be told which (a
    multi-device account with no single online default). Renders the device list the
    bridge attached to the error; falls back to a /devices fetch for an older bridge
    that didn't. The user replies "use <name>" (→ device-use, which persists it).

    ⛔ AND THE FALLBACK CAN LAND ON AN ACCOUNT WITH NONE, which is why it renders the
    empty state rather than a picker with nothing in it. The sentence above used to
    say the account HAS computers as though that were guaranteed; the refetch is
    what decides, and it can come back empty.
    """
    devices = body.get("devices")
    if not isinstance(devices, list) or not devices:
        code, b2 = _get("/devices")
        devices = b2.get("devices", []) if (code == 200 and isinstance(b2, dict)) else []
    devices = [d for d in devices if isinstance(d, dict) and (d.get("name") or d.get("hostname") or d.get("id"))]
    if not devices:
        # No reachable devices after all → the empty state (older bridge path).
        return _no_device_lines()
    if reason == "selection_not_ready":
        # ⛔⛔ NOT "isn't reachable" AND NOT "pick another" ON ITS OWN. The machine
        # is powered on and answering; what it cannot do is take a run, because it
        # is part-way through being set up again. Telling somebody their computer
        # is unreachable sends them to check a network that is fine, and quietly
        # routing the run elsewhere would put their research on a computer they did
        # not choose. The state has a cause and a cure, so both are named.
        lead = ("The computer you’re using is part-way through being set up again, "
                "so it can’t take a run yet. Finish pairing it, or pick another:")
    elif reason == "stale_selection":
        lead = "The computer you last used isn’t reachable anymore — pick another:"
    else:
        # ⛔ THE OBJECT IS AN ARGUMENT, and it has to be. The RUN path says "run
        # this?" because the person just fired it and the object is obvious; the
        # SIGN-IN path has no "this" — it is telling somebody what has been waiting
        # — so it names the topic. `test_the_watchdog_names_the_waiting_topic_and
        # _the_run_path_does_not` pins that difference deliberately, and reusing
        # this renderer for the sign-in door without it silently broke it.
        lead = f"You have {len(devices)} research computers — which should run {about}?"
    lines = [lead]
    for d in devices:
        online = d.get("online")
        dot = " · online" if online is True else (" · offline" if online is False else "")
        lines.append(f"  • {_dev_label(d)}{dot}")
    lines.append(f'Just say: use “{_dev_label(devices[0])}”.')
    return lines


def _signed_in_lines(note) -> list[str]:
    """The one-shot "just signed in" announce, in this client's voice.

    Four outcomes, the same four the watchdog renders and the same four the
    fleet's `login-done` relays: the bridge started the waiting research, there is
    no Research Computer to run it on, several could run it and none is obvious,
    or a topic is simply waiting to be told to go ahead.

    ⛔ EXACTLY ONE LINE FOR A PLAIN SIGN-IN, AND ``[]`` ONLY WHEN THERE IS NO NOTE.
    An earlier version of this sentence claimed ``[]`` for a plain sign-in too, and
    the code has never done that — the difference matters because this read has
    already CONSUMED the announce by the time we get here. Saying nothing would be
    the silent eater again, one function further in: the news would be destroyed
    and the person would never hear it from anybody.

    ⛔ THE "WHICH COMPUTER?" CASE DELEGATES TO ``_pick_device_lines`` RATHER THAN
    WORDING IT AGAIN. That question already exists in two places that a test pins
    against each other, precisely so one question does not get two phrasings
    depending which door the person came through; writing a third here is how the
    third phrasing appears.

    ⭐ THE HEAD IS `_connected_msg`, THE SAME LINE EVERY SIGN-IN ANSWER OPENS WITH,
    AND IT IS ITS OWN BLOCK (owner, 2026-09-25): a blank line separates it from
    whatever the bridge did, so the sign-in and the news never read as one run-on
    paragraph.
    """
    if not isinstance(note, dict) or not note:
        return []
    who = str(note.get("email") or "").strip()
    topic = str(note.get("topic") or note.get("pendingTopic") or "").strip()
    quoted = f"“{topic}”" if topic else "your research"
    head = _connected_msg(who)
    if note.get("autoStarted"):
        where = str(note.get("deviceName") or "").strip()
        # ⛔ "STARTED ON MACBOOK" READS AS WORK IN PROGRESS. Auto-start routes to a
        # persisted selection or a sole computer without consulting power — right,
        # because a sleeping computer takes the work when it wakes — so "started"
        # can mean "queued until somebody switches it on", which could be tomorrow.
        # ⚠ Only an explicit False says so: an absent flag means we do not know,
        # and inventing a wait would be its own falsehood.
        if where and note.get("deviceOnline") is False:
            return [head, "", f"🚀 {quoted} is queued on {where} — it's switched off, "
                              f"so it starts when it comes on."]
        return [head, "", f"🚀 Started {quoted}{(' on ' + where) if where else ''}."]
    if note.get("needsDevice"):
        return [head, ""] + _no_device_lines(lead=f"{quoted} has nowhere to run yet.")
    if note.get("needsDeviceChoice"):
        return [head, ""] + _pick_device_lines(
            {"devices": note.get("devices")},
            "stale_selection" if note.get("staleSelection") else "no_selection",
            about=quoted)
    if topic:
        return [head, "", f"Continue with {quoted}? Say go ahead and I'll start it."]
    return [head]


def cmd_research(args) -> int:
    payload: dict = {"topic": args.topic}
    if args.device:
        payload["deviceId"] = args.device
    # Tag the run with the chat it was fired from, so a per-chat watchdog can
    # scope its updates to this chat only (Telegram→Telegram, WhatsApp→WhatsApp).
    origin = _origin_from_env()
    if origin:
        payload["origin"] = origin
    cfg = {}
    if args.no_video:
        cfg["videoEnabled"] = False
    if args.no_email:
        cfg["emailEnabled"] = False
    if cfg:
        payload["config"] = cfg
    code, body = _post("/research", payload)
    if code != 200:
        # Not signed in (401): give an ACTIONABLE next step, not a dead end. A
        # prior login link expires (~10 min), so steering back to "the link I
        # sent" strands the user — point at a FRESH `login` instead. If a sign-in
        # is already mid-flight, say so (the bridge auto-captures on approval —
        # #848, no `login-done` needed).
        if code == 401:
            # Remember the topic + this chat. ⛔ AND THE COMMENT HERE USED TO
            # DESCRIBE A FLOW THAT NO LONGER RUNS: it said the watchdog would
            # "offer to continue THIS research (confirm-first, never a silent
            # auto-start)". Capture does exactly that auto-start — it claims the
            # topic, resolves a computer and enqueues the run server-side, on by
            # default, before any tick — which is why the line below must not say
            # the research waits on them. Arming decides only whether the announce
            # about it reaches this chat.
            stash = {"pending_topic": args.topic}
            if origin:
                stash["origin"] = origin
            arm_lines, arm_payload, arm_rc = _prepare_stream_arm()
            sc, sbody = _get("/status")
            if sc == 200 and sbody.get("remoteLogin") == "pending":
                # A sign-in is already in flight — attach the topic to it (don't mint
                # a fresh flow, which would void the link they're about to approve).
                pc, pbody = _post("/login/remote/pending", stash)
                # ⛔⛔ THE REPLY IS READ NOW, AND THE FIRST VERSION DISCARDED IT.
                # The bridge refuses when the sign-in already carries somebody
                # else's research (`topic_taken`), and with the reply thrown away
                # this branch went straight on to promise "I'll pick this up" —
                # then nothing ever came. That is the same silent loss the refusal
                # exists to prevent, moved one layer out: two 200-shaped outcomes,
                # one of them a lie.
                if pc == 409 and pbody.get("reason") == "topic_taken":
                    return _emit(pbody, args.json, [
                        "Someone is already signing in on this account with a "
                        "research waiting, so I can't add yours to it yet.",
                        "Ask me again once that sign-in finishes and I'll start it.",
                    ], _fail_code(pc))
                if pc != 200:
                    # ⛔ ANY other refusal — most reachably the 409 the bridge sends
                    # when the sign-in ended between the /status read and this post,
                    # which carries no `reason` at all. Branching only on
                    # `topic_taken` let every other outcome fall through to the
                    # promise below, which is the same silent loss in a different
                    # costume: the topic never landed and the person was told it had.
                    return _emit(pbody, args.json, [
                        "That sign-in just ended, so I couldn't attach your research "
                        "to it.",
                        "Ask me again and I'll start a fresh one.",
                    ], _fail_code(pc))
                # ⛔ THE SECOND HALF OF THIS SENTENCE IS A DELIVERY CLAIM, and it
                # is only true if the arm above actually wrote a cron row — same
                # discriminator as the started-run line further down.
                #
                # ⛔⛔ AND IT MUST NOT REWRITE WHAT THE BRIDGE DOES, which the first
                # version did: it said "then tell me and I'll start it", as though
                # an unwritten cron row stopped the research starting. It does not.
                # Capture claims the topic and starts the run SERVER-SIDE before any
                # tick, whatever this process managed to arm. Arming decides only
                # whether we come back to them about it.
                lines = ["You're almost signed in — finish in your browser and "
                         "I'll pick this up"
                         + (". I'll post here when it's done."
                            if arm_payload.get("armed")
                            else " — ask me once you're in and I'll tell you where "
                                 "it got to.")]
                if arm_rc == 0 and arm_lines:
                    lines += _agent_directive_block(arm_lines)
                return _emit(body, args.json, lines, _fail_code(code))
            # No flow yet: start one carrying the topic, hand back the click-to-approve
            # link, and the bridge captures it automatically on approval (#848).
            lc, lbody = _post("/login/remote/start", stash)
            # ⛔ THE SAME REFUSAL REACHES THIS DOOR TOO. A flow can appear between
            # the /status read above and this call, and the bridge refuses a start
            # that would void somebody else's waiting research. Without this the
            # branch falls through to "tell me to log you in", which is neither
            # true nor the next step.
            if lc == 409 and lbody.get("reason") == "topic_taken":
                return _emit(lbody, args.json, [
                    "Someone is already signing in on this account with a research "
                    "waiting, so I can't start yours yet.",
                    "Ask me again once that sign-in finishes.",
                ], _fail_code(lc))
            link = lbody.get("verifyUrl") if lc == 200 else None
            if link:
                lines = [
                    ("You're not signed in yet. Log in here and I'll pick this "
                     "up — I'll post here when it's done:"
                     if arm_payload.get("armed") else
                     "You're not signed in yet. Log in here and I'll pick this "
                     "up — ask me once you're in:"),
                    f"  {link}",
                ]
                if arm_rc == 0 and arm_lines:
                    lines += _agent_directive_block(arm_lines)
                return _emit({**body, "verifyUrl": link}, args.json, lines, _fail_code(code))
            return _emit(body, args.json, [
                "You're not signed in yet — tell me to log you in and I'll send a link.",
            ], _fail_code(code))
        # Signed in but the run couldn't be routed to a device. Tell the two cases
        # apart by the bridge's machine-readable `reason` (NOT an English substring —
        # "no device selected" and "no devices yet" both contain "no device", so the
        # old substring test mis-sent a MULTI-device account to the "install a backend
        # here" prompt). no_devices → pair/install one; no_selection/stale_selection →
        # the account HAS computers, ask which. Older bridge (no reason): infer from text.
        err = str(body.get("error", "")).lower()
        reason = body.get("reason")
        # ⛔⛔ HIDDEN COUPLING WITH bridge.py's no_devices REFUSAL TEXT, and it
        # is a prose rename with a behavioural consequence. This fallback reads
        # the bridge's ENGLISH, so when wave 9 renamed "pair code" to the web's
        # "access code" in that sentence, matching only the new wording would
        # have silently lost the no-device empty state for every INSTALLED
        # bridge older than the rename — the person would drop through to the
        # bare "couldn't start" line instead. BOTH spellings are matched on
        # purpose, and neither may be removed while an older bridge can still be
        # on disk. See the matching note at bridge.py's `reason == "no_devices"`.
        if not reason:
            reason = ("no_devices" if ("no devices yet" in err
                                       or "grab the access code" in err
                                       or "grab the pair code" in err)
                      else ("no_selection" if "no device" in err else ""))
        if reason == "no_devices":
            # ⭐⭐ THE TOPIC IS HELD, AND THE PERSON HAS TO BE TOLD SO. The bridge
            # parks it when the ask came from a chat, and starts it by itself the
            # moment a computer arrives — which is only a kindness if it was
            # promised. Unannounced it is research starting on its own, minutes or
            # hours later, for a reason nobody can see.
            #
            # ⛔ CONDITIONAL ON THE ORIGIN, because the park is. Without one the
            # bridge holds nothing (there would be no chat to tell), so promising
            # it here would be a claim this client cannot keep.
            # ⚠ `origin` and `args.topic` — not a local named `topic`, which does
            # not exist in this function and which ruff caught before any test
            # did. The origin was already resolved at the top of the call.
            lead = (f"“{args.topic}” has nowhere to run yet — I’ll hold it and "
                    "start it as soon as you have a computer."
                    if origin else None)
            return _emit(body, args.json, _with_empty_state_relay(_no_device_lines(lead)),
                         _fail_code(code))
        if reason in ("no_selection", "stale_selection", "selection_not_ready"):
            return _emit(body, args.json, _pick_device_lines(body, reason), _fail_code(code))
        return _emit(body, args.json, [f"✗ couldn't start: {body.get('error', code)}"], _fail_code(code))
    dev = _device_names().get(body.get("deviceId") or "", body.get("deviceId") or "")
    where = f" on {dev}" if dev else ""
    # Auto-arm THIS chat's run-scoped streaming watchdog so progress posts without
    # the user asking — _prepare_stream_arm writes the cron row into jobs.json itself
    # (idempotent), so nothing needs the AI here; arm_lines is empty on success and
    # only carries a fallback directive if the direct write couldn't run. On a prep
    # error, skip silently: the run is fine and `status` still works.
    #
    # ⛔⛔ AND IT IS READ NOW, BECAUSE THE PROMISE BELOW DEPENDS ON IT. "I'll post
    # here when it's done" was printed unconditionally, three lines above the call
    # that decides whether anything will ever post. Nothing in this package
    # schedules: the only thing that ticks is a cron row in the host runtime's own
    # store, and `_prepare_stream_arm` reports whether one was actually written.
    #
    # ⚠ `armed` MEANS "THIS PROCESS WROTE THE ROW", AND NOTHING STRONGER. An
    # earlier version of this comment said a no-origin runtime "can never be
    # delivered to", which this same file contradicts twice — `_stream_health_lines`
    # returns True there because the account-wide watchdog streams every agent run,
    # and the directive handed over on that branch asks the assistant to arm one.
    # False therefore means "we did not write it and cannot vouch for it", on both
    # the legacy branch and a jobs.json we could not write. That is the right gate
    # for what we may PROMISE, and the wrong one for what will happen.
    arm_lines, arm_payload, arm_rc = _prepare_stream_arm()
    lines = [f"🚀 Started “{args.topic}”{where}."]
    if arm_payload.get("armed"):
        lines.append("I’ll post here when it’s done — and if it ever needs you. "
                     "Ask how it’s going anytime.")
    else:
        # ⭐ NO APOLOGY AND NO MECHANISM. What is left is still a complete answer:
        # the research is running and asking is how they hear about it.
        lines.append("Ask me how it’s going anytime — I’ll have the brief, "
                     "reports and podcast right here.")
    if arm_rc == 0 and arm_lines:
        lines += _agent_directive_block(arm_lines)
    return _emit(body, args.json, lines)


def cmd_status(args) -> int:
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    run = _pick_run(runs, args.runId, prefer_active=True)
    if run is None:
        which = f"matching “{args.runId}”" if args.runId else "yet"
        return _emit(body, args.json, [f"No runs {which}."])
    rid = run.get("runId")
    code, b2 = _get(f"/research/{urllib.parse.quote(rid, safe='')}")
    if code != 200:
        return _emit(b2, args.json, [f"✗ {b2.get('error', code)}"], _fail_code(code))
    r = b2.get("research", {})
    title = r.get("title") or r.get("topic") or rid
    dev = _device_names().get(r.get("deviceId") or "", "")
    where = f"  ·  {dev}" if dev else ""
    # A queued run has no phase yet (the BE stamps it at start) — show the
    # place in line instead of a confusing "queued (phase ?)".
    if r.get("status") == "queued":
        qp = r.get("queuePosition")
        stat = f"queued — #{qp} in line" if qp else "queued — waiting for a free worker"
    else:
        stat = f"{r.get('status', '?')} (phase {r.get('phase', '?')})"
    lines = [f"“{title}” — {stat}{where}"]
    lines += _fmt_pipeline_config(r.get("pipelineConfig"))
    lines += _attention_lines(r)
    # Per-phase plan = the curated links (🔒 SR for Brief/reports/Podcast, 🔗 platform
    # for NotebookLM/YouTube/Doc). If the bridge supplied none yet (no phase done, or
    # an older build), fall back to the minted permanent SR links — never the raw,
    # tokenized Storage audio URL.
    phase_updates = b2.get("phaseUpdates")
    if phase_updates:
        lines += _fmt_phase_updates(phase_updates)
    else:
        lines += _fmt_sr_links(b2.get("srLinks") or {})
    # Watchdog self-heal: if an agent run is live but this chat's watchdog
    # isn't ticking, re-emit the arming directive (see _stream_health_lines).
    lines += _stream_health_lines(runs)
    return _emit(b2, args.json, lines)


def cmd_podcast(args) -> int:
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    if args.runId:
        run = _pick_run(runs, args.runId)
    else:
        # The podcast audio is a late-phase artifact — prefer the newest run that
        # already HAS audio over the newest active run (which usually has none yet).
        with_audio = [r for r in runs
                      if any(lk.get("kind") == "audio_file" for lk in r.get("links", []))]
        run = with_audio[0] if with_audio else (runs[0] if runs else None)
    if run is None:
        which = f"matching “{args.runId}”" if args.runId else "yet"
        return _emit(body, args.json, [f"No runs {which}."])
    rid = run.get("runId")
    # The bridge downloads the audio to a local file (a long audio overview can
    # take a few seconds) → allow more time than the default request timeout.
    # Tell the bridge which chat this is headed to: upload ceilings are the
    # PLATFORM's and differ by an order of magnitude (Telegram 50 MB vs WhatsApp
    # ~16 MB), so a file that is fine here is refused there.
    origin = _origin_from_env() or {}
    platform = (origin.get("platform") or "").strip()
    q = f"?platform={urllib.parse.quote(platform, safe='')}" if platform else ""
    code, b2 = _get(f"/research/{urllib.parse.quote(rid, safe='')}/podcast{q}", timeout=180)
    if code != 200:
        return _emit(b2, args.json, [f"✗ {b2.get('error', code)}"], _fail_code(code))
    title = b2.get("title") or "Podcast"
    if b2.get("tooLarge"):
        # Past the chat platform's upload ceiling even after re-encoding. Sending a
        # path here would be worse than useless: the platform refuses the upload and
        # the runtime degrades to printing the path as text (live 2026-07-26 — an
        # 89-minute overview came back as a dead file path). Hand over the permanent
        # link instead, which plays in the browser and never expires.
        share = b2.get("shareUrl") or ""
        lines = [f"🎧 {title}"]
        if share:
            lines += ["It's too long to send as a file here — listen at:", f"  {share}"]
        else:
            lines.append("It's too long to send as a file here — ask for the links "
                         "and I'll get you the podcast link.")
        return _emit(b2, args.json, lines)
    # Emit a short caption + an explicit MEDIA:<path> tag on its own line. The
    # runtime's gateway extracts MEDIA: tags into its AUDIO partition, which
    # delivers the file as native PLAYABLE audio (Telegram sendAudio for
    # mp3/m4a; other platforms' voice/audio sender) and strips the tag from
    # the visible text — so the user sees the title + an inline player. A BARE
    # path is NOT equivalent: bare paths route to document delivery (a "📎
    # File" attachment, not playable — the 2026-07-02 live failure). Do NOT
    # add [[audio_as_voice]]: it suppresses the text body (voice-reply dedup)
    # and only matters for .ogg/.opus voice bubbles.
    # The MEDIA contract keeps breaking on AI paraphrase (live 2026-07-06: the
    # assistant rewrote the MEDIA: line to "🔊 Audio: <path>", which routes to
    # document delivery instead of the native player, and the user had to ask
    # "make it playable" a second time). Ship the instruction WITH the output
    # under the do-not-relay marker so it's in front of the model at the exact
    # moment it relays — not buried in SKILL.md's per-command notes.
    return _emit(b2, args.json, [
        f"🎧 {title}",
        f"MEDIA:{b2.get('localPath')}",
        *_agent_directive_block([
            "Reply with the TWO lines above EXACTLY as printed — the MEDIA: line",
            "verbatim on its own line. Do NOT decorate, relabel, or rewrite it",
            "(no emoji prefix, no speaker/label word before the path, no code",
            "block, no bare path): the gateway converts the exact MEDIA: line",
            "into a native playable audio message in this chat; any rewrite",
            "turns it into a non-playable file path.",
        ]),
    ])


def cmd_updates(args) -> int:
    # via_agent → agent-only runs + per-phase SR-link minting (same clean links
    # the streaming watchdog posts).
    code, body, runs = _fetch_runs(active=args.active, via_agent=True)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    # ⛔⛔ THIS READ TAKES THE ONE-SHOT SIGN-IN ANNOUNCE, AND IT USED TO THROW IT
    # AWAY. `?via=agent` is the bridge's sole take-and-clear trigger, and this
    # call carries no chat scope — so it takes an ORIGIN-LESS announce, racing the
    # account-wide watchdog for it. (⚠ It does NOT take a chat-scoped one: that is
    # put straight back for the watchdog that owns it. An earlier version of this
    # comment said the bridge "does not care which reader asked", which is wrong
    # and would have sent somebody looking for a leak that cannot happen.) An
    # `updates` call consumed the announce, moved the delivered-watermark with it,
    # and then rendered runs only. The person heard nothing about the sign-in from this command, and the
    # watchdog that would have said it two minutes later found the note gone AND
    # the watermark past it, so the re-mint could not recover it either. Silent,
    # permanent, and produced by somebody asking a perfectly reasonable question.
    #
    # ⭐ RENDER IT, DO NOT PEEK. Taking is right — it is what stops the watchdog
    # saying the same news again a minute later — and it is exactly what the
    # fleet's `login-done` already does with the same call. The rule the take
    # implies is the one that was broken: whoever takes this note OWES the person
    # its contents. Every other `via=agent` reader in the tree already pays it.
    lines = _signed_in_lines(body.get("signedIn"))
    if lines:
        # ⭐ Two blocks, not one run-on (owner, 2026-09-25): the sign-in, a blank
        # line, then the runs.
        lines.append("")
    for r in runs:
        # A queued run has no phase yet — show its place in line (mirrors status).
        if r.get("status") == "queued":
            _qp = r.get("queuePosition")
            _stat = f"queued — #{_qp} in line" if _qp else "queued — waiting for a free worker"
        else:
            _stat = f"{r.get('status')} (phase {r.get('phase')})"
        lines.append(f"“{r.get('title') or r.get('topic')}” — {_stat}")
        lines += _fmt_pipeline_config(r.get("pipelineConfig"))
        lines += _attention_lines(r)
        phase_updates = r.get("phaseUpdates")
        if phase_updates:
            lines += _fmt_phase_updates(phase_updates)
        else:
            # Fallback (older build / no phaseUpdates): the minted permanent SR links.
            lines += _fmt_sr_links(r.get("srLinks") or {})
    # ⛔ KEYED ON `runs`, NOT ON `lines`. Seeding `lines` with the sign-in announce
    # made the old `lines or [...]` fallback dead: somebody who asked what was
    # running got a sign-in line and NO statement about their runs at all, which is
    # a different way of not answering the question they asked.
    if not runs:
        lines.append("No active runs.")
    # Watchdog self-heal: re-emit the arming directive when a live agent run
    # has no ticking watchdog in this chat (see _stream_health_lines).
    tail = _stream_health_lines(runs)
    # ⛔⛔ THE NO-COMPUTER SCREEN RODE THROUGH HERE WITH NO RELAY RULE (2026-09-24).
    # A taken announce that says there is nowhere to run renders the whole screen
    # above, and this was the one door that printed it bare — missing even from
    # `_with_empty_state_relay`'s own list of uncovered sites. The rule has to be
    # the LAST thing printed, and the re-arm directive is already a block under
    # the marker, so the rule JOINS that block as its last line rather than
    # opening a second marker.
    # ⚠ Keyed the way `_signed_in_lines` branches: `autoStarted` is checked first
    # there, so only a note that did not start anything renders the screen.
    signed_in = body.get("signedIn")
    if (isinstance(signed_in, dict) and signed_in.get("needsDevice")
            and not signed_in.get("autoStarted")):
        tail = ([*tail, _EMPTY_STATE_RELAY] if tail
                else _agent_directive_block([_EMPTY_STATE_RELAY]))
    return _emit(body, args.json, lines + tail)


# ── send logs ────────────────────────────────────────────────────────────────
#
# ⛔⛔ THIS IS A CONFIRM-FIRST VERB AND THE REASON IS NOT POLITENESS. The
# research computer refuses a request that does not carry recorded consent, and
# that flag is a claim that a person was SHOWN what leaves their machine. In the
# app a modal makes the claim true. Here the FIRST call prints what would be
# sent and sends nothing; only `--confirm` puts the flag on the wire. A single
# call that showed the person nothing and claimed consent anyway would be
# forging the one thing the machine cannot check for itself.
#
# ⭐ A SECOND COPY OF THE CLI'S SENTENCES, AND THE DUPLICATION IS FORCED. This
# script is stdlib-only by contract — it runs inside somebody else's chat
# runtime and may not import `facade` — so it cannot share the table.
# `test_send_logs_cli_0825.py` reads both files and fails if either grows a case
# the other lacks.
_SEND_LOGS_FAILURES = {
    # ⛔⛔ NAMES NO DURATION, AND NAMES NO CULPRIT. Two windows — 600s for your
    # own second press, 60s when anybody else who uses that computer went
    # first — and the refusal names neither. See the note in cli.py.
    "CooldownActive": "that computer built a bundle very recently, and its "
                      "limit counts everyone who uses it — so it may not have "
                      "been you. Try again shortly",
    "AlreadyBuilding": "that computer is already packaging a bundle — wait for "
                       "it to finish and ask again",
    "NotDeviceMember": "that computer no longer counts you as one of its "
                       "people, so it will not package anything for you",
    "NotDeviceOwner": "only the person who owns that computer can ask for its "
                      "own logs",
    "NothingSelected": "nothing was chosen to send",
    "ConsentMissing": "that computer was not told the request had been agreed "
                      "to — this is a bug on our side, please report it",
    "RunsInvalid": "that computer could not read the selection — this is a bug "
                   "on our side, please report it",
    "SubmitterMissing": "that computer could not tell who was asking — this is "
                        "a bug on our side, please report it",
    "DeviceReadFailed": "that computer could not look itself up, which usually "
                        "means it has lost its connection",
    # ⛔ NOT `--doctor` — it prints no bundle path. See the note in cli.py.
    "UploadFailed": "the bundle was built but could not be uploaded — it is "
                    "still on that computer, under its Super Research logs "
                    "folder",
}

_SEND_LOGS_UNKNOWN = ("that computer refused the request and gave a reason we "
                      "do not have a sentence for")


def _send_logs_failure(error_class: str) -> str:
    """A refusal in words a person can act on. ⛔ Never empty and never the bare
    class name — an error nobody can read is the same as no error at all."""
    known = _SEND_LOGS_FAILURES.get(str(error_class or ""))
    if known:
        return known
    return f"{_SEND_LOGS_UNKNOWN} ({error_class})" if error_class else _SEND_LOGS_UNKNOWN


def _size_words(n) -> str:
    try:
        size = float(n or 0)
    except (TypeError, ValueError):
        return "unknown size"
    for unit, step in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if size >= step:
            return f"{size / step:.1f} {unit}"
    return f"{int(size)} bytes"


def _log_run_label(row: dict) -> str:
    """⭐ The title if this account still holds one, otherwise the date. A run
    whose research is gone from the app keeps its row — those logs are still on
    that disk, and are often exactly the ones worth sending."""
    title = (row.get("title") or "").strip()
    if title:
        return title
    started = (row.get("startedUtc") or "").strip()
    return f"a run from {started[:10]}" if started else "an unnamed run"


# ⭐ THE SAME TWO TOKENS THE TERMINAL TAKES, duplicated here for the same reason
# every other send-logs sentence in this file is: this script must be stdlib-only
# and cannot import the facade package, so it carries its own copy.
#
# ⛔ AND THE POLICING IS NARROWER THAN IT LOOKS. `test_send_logs_cli_0825.py`
# compares the two FAILURE TABLES, not this vocabulary — an earlier version of
# this comment claimed otherwise and was wrong. What compares the tokens is
# `test_chat_and_the_terminal_agree_on_every_spec` in
# `test_send_logs_picker_791.py`, which drives BOTH resolvers over the same specs
# and asserts identical answers. The two have already drifted once (this file
# splits on spaces and drops spoken connectives; the terminal does neither,
# because nobody speaks to it), so the agreement list is where a new token must
# be added, not this comment.
_AGENT_LOG_TOKEN = "0"
_ALL_TOKEN = "all"
# The words a person puts between numbers when they say a list out loud. Dropped
# before tokenising, never treated as a run.
_SPOKEN_FILLER = frozenset({"and", "&", "+", "plus", "then", "also", "the", "run",
                            "runs", "number", "numbers", "no", "no.", "#"})


def _resolve_log_selection(rows: list, spec) -> tuple:
    """Turn a `--runs` spec into (run names, whether the agent's own log was
    asked for, lines explaining a refusal). A non-empty third element IS the
    refusal — names is None then, so a caller that forgets to check cannot go on
    and send an empty selection as though it were a chosen one.

    ⛔⛔ CHAT COULD NOT EXPRESS A SUBSET AT ALL BEFORE THIS. The client picked
    every run the machine listed and offered exactly one way to change that —
    `--none`, which picks nothing. So a person in a chat asking to send the logs
    for one research had two answers available: all of them, or none, and the
    assistant relaying for them had no third. The wire has always accepted an
    arbitrary list; only the client could not name one.

    ⛔ REFUSES ON ANYTHING IT CANNOT PLACE, exactly as the terminal does. A
    dropped token is a run somebody asked for, not sent, reported as success."""
    known = {r.get("name") for r in rows}
    picked = []
    wants_agent_log = False
    # ⛔⛔ A PERSON SAYS "1 AND 3", NOT "1,3". The assistant relays words, so the
    # spec arrives as somebody's sentence rather than as a shell argument — and
    # splitting on whitespace alone half-accepted it: "1 and 3" refused on the
    # word "and", naming a run called “and”. The connectives are dropped, and
    # anything else that is not a number still refuses, because a token this
    # cannot place is a run somebody asked for and did not get.
    #
    # ⛔ ONLY WHEN IT IS NOT A RUN NAME. A machine is free to mint a run called
    # "and"; if this list is holding one, the word means that run.
    for token in str(spec or "").replace(" ", ",").split(","):
        token = token.strip()
        if not token:
            continue
        if token.lower() in _SPOKEN_FILLER and token not in known:
            continue
        if token == _AGENT_LOG_TOKEN:
            wants_agent_log = True
            continue
        if token.lower() == _ALL_TOKEN:
            for row in rows:
                if row.get("name") not in picked:
                    picked.append(row.get("name"))
            continue
        # ⛔ `isdecimal`, NOT `isdigit`, and at most ONE sign — the terminal's
        # twin. "²".isdigit() is True and int("²") raises; "+-1" survives
        # `lstrip("+-")` and int() refuses it too. A traceback is not a sentence.
        body_ = token[1:] if token[:1] in "+-" else token
        if body_.isdecimal() and body_.isascii():
            index = int(token)
            if not 1 <= index <= len(rows):
                # ⛔ "numbered 1 to 0" IS NOT A SENTENCE. When that computer
                # listed nothing there is no range to quote, and the person needs
                # the other fact — that there is nothing to pick from.
                if not rows:
                    return None, False, ["That computer hasn’t listed any runs, "
                                         "so there are no numbers to pick — 0, "
                                         "the agent’s own log, still needs a "
                                         "bundle to ride."]
                return None, False, [f"There’s no {index} in that list — the runs "
                                     f"are numbered 1 to {len(rows)}, and 0 is the "
                                     "agent’s own log."]
            name = rows[index - 1].get("name")
        elif token in known:
            name = token
        else:
            return None, False, [f"That computer isn’t holding a run called "
                                 f"“{token}”."]
        if name not in picked:
            picked.append(name)
    return picked, wants_agent_log, []


def _agent_log_only_request(args) -> bool:
    """True when the ONLY thing being asked for is this host's own agent log.

    ⛔⛔ THIS DECIDES WHETHER A DEVICE IS NEEDED AT ALL, which is why it runs
    before the run list is fetched rather than after. The person who most needs to
    send this file is the person with no research computer, or one they cannot
    reach — and `/logs/runs` refuses both of those with "pick a computer". Asking
    it first would turn the one request that needs no machine into the one request
    a machineless person cannot make.

    ⛔ `--agent-log` ON ITS OWN IS NOT THIS. Bare, it means "everything this
    computer is holding, and the agent's log as well" — the runs default to every
    listed row. Only an explicit "and nothing else" (`--none`, or a `--runs` spec
    naming just the 0) says the log is the whole request.

    ⛔⛔ `--list` DISQUALIFIES IT TOO, AND ITS ABSENCE WAS A LIVE REGRESSION.
    `--list` means "show me what it is holding and send nothing" — the one flag on
    this command that promises no side effect at all. The early return sits above
    the `if args.list: return 0` short-circuit, so `send-logs --list --runs 0 -y`
    printed the standalone plan and UPLOADED. Found by cross-verification, which
    ran it.

    ⛔ AND `--machine` DISQUALIFIES IT outright: that is material from a research
    computer, so there is a computer in the request.
    """
    if bool(getattr(args, "machine", False)):
        return False
    # ⛔ SEE THE NOTE ABOVE — `--list` sends nothing, ever.
    if bool(getattr(args, "list", False)):
        return False
    spec = [t.strip() for t in
            str(getattr(args, "runs", "") or "").replace(" ", ",").split(",")
            if t.strip()]
    if not (bool(getattr(args, "agent_log", False)) or _AGENT_LOG_TOKEN in spec):
        return False
    if [t for t in spec if t != _AGENT_LOG_TOKEN]:
        return False
    return bool(getattr(args, "none", False)) or bool(spec)


def _agent_log_machine_hint(args) -> tuple:
    """(may we offer --machine, what to call that computer) — BEST EFFORT ONLY.

    ⛔⛔ A FAILURE HERE COSTS THE HINT AND NOTHING ELSE, and that is the whole
    distinction this branch turns on. It exists so somebody with no research
    computer can send the agent's log, and `/logs/runs` is precisely the call that
    refuses those people — so its answer is used when it arrives and ignored when
    it does not. It may never decide whether the send happens.

    ⛔ AND THE OFFER STAYS OWNER-ONLY. `--machine` is refused for anybody else, so
    offering it to a sharer walks them into a refusal an earlier wave closed on
    this exact branch.

    ⛔ NO HINT AT ALL WHEN A COMPUTER WAS NAMED. Resolving `--device` costs another
    round trip, and naming the SELECTED machine in a sentence about the one they
    asked for would be a wrong statement rather than a missing one.
    """
    if getattr(args, "device", "") or "":
        return False, ""
    code, body = _get("/logs/runs")
    if code != 200 or not body.get("owned"):
        return False, ""
    return True, str(body.get("deviceName") or "your Research Computer")


def _bundle_waiting_lines(code: str, body: dict) -> "list[str]":
    """What to say about a support bundle whose row has not appeared.

    ⛔⛔ THE THREE CAUSES ARE DIFFERENT ADVICE, AND THEY WERE ONE SENTENCE. A
    machine that has taken the request and is zipping needs patience; a machine
    that has not taken it and is not answering needs something else entirely, and
    telling somebody to keep waiting for it is telling them to wait for nothing.

    ⛔ `picked` IS ABSENT WHEN THIS BRIDGE DID NOT MINT THE CODE — a restart since
    the send, or a code from another host. Then there is genuinely nothing to
    distinguish and the old honest ambiguity is the right answer; it is the
    fallback rather than the default.

    ⛔ AND LIVENESS NEVER TURNS INTO "IT IS OFF". A late heartbeat reads the same
    as a dead machine, so the words stay "isn't answering".
    """
    name = str(body.get("deviceName") or "that computer")
    picked = body.get("picked")
    online = body.get("deviceOnline")
    age = int(body.get("ageSeconds") or 0)
    waited = f" It’s been {_age_words(age)}." if age >= 120 else ""

    if picked is True:
        lines = [f"Nothing has come back for {code} yet, but “{name}” HAS picked "
                 f"the request up — it’s packaging it.{waited}"]
        if age > 900:
            lines.append("That’s longer than packaging usually takes, so it may "
                         "have stopped partway. Ask me again in a bit.")
    elif picked is False and online is False:
        # ⛔⛔ THE ONE TERMINAL CASE, AND IT IS WORTH STATING PLAINLY. The device's
        # stale gate MARKS rather than deletes, so an unread command sits there
        # indefinitely — a machine that is not answering has not read it and will
        # not until it comes back. Saying "wait" here would be false.
        lines = [f"“{name}” hasn’t picked up the request for {code}, and it isn’t "
                 f"answering right now.{waited}",
                 "Nothing will arrive until that computer is back on — the "
                 "request keeps until then."]
    elif picked is False:
        lines = [f"“{name}” is answering, but hasn’t picked up the request for "
                 f"{code} yet.{waited}"]
    else:
        # the honest ambiguity, for when we genuinely cannot tell
        lines = [f"Nothing has come back for {code} yet. “{name}” may still be "
                 "packaging it, or may not have picked the request up."]

    # ⛔ AND THE HALF THAT DID ARRIVE IS NAMED, because on this branch it is the
    # only thing support can actually read. It is easy to forget it went at all
    # when the message is about the half that did not.
    other = str(body.get("agentLogCode") or "")
    if other:
        lines.append(f"The agent’s own log did go, separately — quote {other} for "
                     "that half.")
    return lines


def _age_words(seconds: int) -> str:
    if seconds < 120:
        return f"{seconds} seconds"
    if seconds < 5400:
        return f"{seconds // 60} minutes"
    return f"{seconds // 3600} hours"


def _wants_agent_log(args) -> bool:
    """True when this request includes the agent's own log — decided from the
    ARGUMENTS ALONE, with no run list.

    ⛔⛔ IT HAS TO BE ANSWERABLE BEFORE `/logs/runs`. The local half is uploaded
    up front now, before the run list is fetched and before the research computer
    is asked for anything, so the question has to be answerable at a point where
    no rows exist yet. `_resolve_log_selection` answers the same question a second
    time, from the matched rows; the two agree because both read the same `0`
    token, this one off the raw `--runs` string and that one after matching.

    ⛔ THIS IS NOT `_agent_log_only_request`. That one asks "is the log the WHOLE
    request?" and routes to a different command entirely. This one asks "is the
    log IN the request?", which is true of the combined shape too — and the
    combined shape is the one that was losing it.
    """
    spec = [t.strip() for t in
            str(getattr(args, "runs", "") or "").replace(" ", ",").split(",")
            if t.strip()]
    return bool(getattr(args, "agent_log", False)) or _AGENT_LOG_TOKEN in spec


def _send_agent_log_now(args) -> "tuple[str, list[str]]":
    """Upload this host's agent log on its own, right now, and say what happened.

    ⭐⭐ THE LOCAL FILE STOPS WAITING FOR A REMOTE MACHINE. It used to be deferred:
    the confirmed send printed "the agent's own log goes up once that computer's
    bundle lands" and handed the assistant `--status <CODE> --agent-log`, which the
    bridge refuses until the machine's row exists. On 2026-09-20 the machine never
    answered, so the refusal never lifted, and a file sitting readable on THIS
    disk — needing no device, no permission and nobody's cooperation — was lost
    along with a bundle it had no reason to be attached to.

    ⛔ THE REASON FOR THE DEFERRAL IS GONE, NOT IGNORED. It existed because the
    app's Clear-logs button finds objects by listing each ROW's folder, so an
    object written before a row exists is a log the privacy button can never
    reach. The standalone route mints its own code and opens its own row BEFORE
    the object, which satisfies that invariant without any machine — so this is
    not a relaxation of the rule, it is the rule being met a different way.

    ⛔ AND IT CARRIES `consent`, exactly as `/logs/send` does. The plan that
    listed this file, its three disclosures and its retention was printed on the
    branch above; this claims that happened. Without it the bridge refuses, so an
    assistant that skips the plan and jumps to `--confirm` cannot cause an
    immediate upload of a file naming a masked email and a whole sign-in trail.

    ⛔ NEVER FATAL. The machine's request has not been made yet when this runs, so
    there is nothing in flight to damage, and a failure here is reported as its
    own sentence rather than taking the rest of the send down with it.
    """
    code, sent = _post("/logs/agent-log", {"standalone": True, "consent": True})
    if code != 200:
        return "", [f"⚠ The agent’s own log didn’t go: "
                    f"{sent.get('error', code)}. Nothing else was affected."]
    if not sent.get("sent"):
        # ⭐ A fact, not a failure — and no code, because nothing was stored.
        return "", ["The agent’s log on this host was empty — there was nothing "
                    "to send from here."]
    support = str(sent.get("code") or "")
    return support, [f"✓ Sent the agent’s own log from this host. Its support "
                     f"code is {support}."]


def _agent_log_facts() -> list:
    """What a person is told before this file leaves, in both clients.

    ⛔⛔ ONE SOURCE, BECAUSE THE TWO PLANS DRIFTED ONCE ALREADY. These sentences
    are printed from two places in this file now — beside a machine's bundle and
    on its own — and a guard compares the CLAIMS against the terminal's twin. A
    second hand-written copy is how one of the three quietly stops being said.
    """
    return [
        # ⛔⛔ WHOSE, NOT ONLY WHAT. A second person who signed in on this host is
        # in that file, and nothing gates the upload on who owns the host, because
        # an agent host has no owner to ask.
        "It covers everyone who signed in through this agent, not only you — "
        "there’s no owner to ask on a machine like that, so nothing checks.",
        # ⛔⛔ THE ROTATED COPIES GO TOO, SINCE WAVE 8 — and this sentence changed
        # with the material rather than after it. It used to say "since that file
        # last rotated", which was true of a reader that sent the active file and
        # only the active file, and understates what leaves now.
        "The rotated copies go too, not only the newest file, so it reaches back "
        "further than the problem you’re reporting.",
        # ⛔⛔ NAMED, because "not research content" is what it is NOT. Measured in
        # the file the uploader reads.
        "Among what’s in it: a masked form of your email address, the ids of the "
        "computers and runs this agent has touched, file paths on that machine, "
        "and — when a lookup fails — your account id.",
    ]


def _send_agent_log_alone(args, offer_machine: bool = False, name: str = "") -> int:
    """Send this host's agent log with NO bundle behind it, under its own code.

    ⛔⛔ THIS IS WHAT THE REFUSAL USED TO BE. Until wave 8 the only answer here was
    "the agent's own log can only go up beside a bundle from that computer", which
    was true of the transport and useless to the person reading it: the two
    commonest reasons to be sending an agent log are having no research computer
    and having one you cannot reach, and neither of those can produce a bundle.
    The app mints a support code for it now, so this is a send like any other.

    ⛔ STILL TWO STEPS. Nothing leaves without `--confirm`, and the plan printed
    here is what makes `consent` true — the same rule the bundle path follows.
    """
    if not getattr(args, "confirm", False):
        lines = [
            "I can send Super Research support the log from the agent on THIS "
            "host — the machine running this chat. No research computer is "
            "involved, and nothing from one is included.",
            "It’s a connection and sign-in record, not research content.",
            *_agent_log_facts(),
            "It’s deleted automatically 30 days after it arrives.",
            "You’ll get a support code of its own to quote.",
        ]
        directives = [
            "If they say yes, run: sr.py send-logs --confirm --agent-log --none",
            "⛔ That sends the agent’s log and NOTHING from any research "
            "computer. It needs no device and no support code.",
        ]
        if offer_machine:
            # ⛔ ONLY TO AN OWNER. `--machine` is refused for anybody else, so
            # offering it to a sharer sends them into a refusal this line could
            # have spared them — the circle a previous wave closed here.
            lines.append(
                f"If the trouble is reaching “{name}” at all, I can ask for that "
                "computer’s own logs as well — say so and they’ll go together.")
            # ⛔⛔ AND THE COMMAND THAT DELIVERS IT, or the offer is a sentence with
            # nothing behind it. The directive above sends the agent's log ALONE,
            # so an assistant relaying an offer it cannot carry out is the same
            # shape as the refusal-in-a-circle an earlier wave closed: the words
            # say yes and the only command on the screen says no.
            directives.append(
                "If they want that computer’s own logs too, run instead: sr.py "
                "send-logs --confirm --machine --none --agent-log")
        lines.append("Say yes and I’ll send it.")
        # ⛔⛔ `--json` PRINTS THE PAYLOAD *INSTEAD OF* THE LINES, so a plan whose
        # whole job is disclosure disclosed nothing at all on that path — and
        # `wouldSend: []` read as "nothing would be sent" about a call that sends a
        # file. Everything the words say is in the payload now, because the relay
        # reading JSON is relaying to a person either way.
        return _emit({"wouldSend": [], "includeMachine": False,
                      "agentLogOnly": True, "agentLogWouldSend": True,
                      "retentionDays": 30, "consentIncluded": _agent_log_facts(),
                      "plan": lines},
                     args.json, [*lines, *_agent_directive_block(directives)])

    code, sent = _post("/logs/agent-log", {"standalone": True})
    if code != 200:
        return _emit(sent, args.json,
                     [f"✗ the agent’s log didn’t go: {sent.get('error', code)}"],
                     _fail_code(code))
    if not sent.get("sent"):
        # ⭐ A fact, not a failure — and there is no code, because nothing was
        # stored. An agent whose log is empty has nothing to say.
        return _emit(sent, args.json,
                     ["The agent’s log on this host was empty — there was nothing "
                      "to send."])
    support = sent.get("code", "")
    return _emit(sent, args.json, [
        f"✓ Sent the agent’s own log. Your support code is {support}.",
        "Quote it when you report the problem.",
    ])


def cmd_send_logs(args) -> int:
    """Ask the research computer to package its logs for support.

    Two steps by design — see the block comment above. Without ``--confirm``
    this prints what would be sent and sends nothing.
    """
    if args.status:
        want = str(args.status).strip().upper()
        code, body = _get(f"/logs/bundle?code={want}")
        if code != 200:
            return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
        row = body.get("row")
        if not row:
            # ⭐⭐ THREE DEFINITE ANSWERS, NOT ONE AMBIGUITY REPEATED. This branch
            # said "may still be packaging it, or may not have picked the request
            # up" and nothing else — and on 2026-09-20 a person was told exactly
            # that, four times over seventeen minutes, while the fact that settled
            # it was one Firestore read away. The machine DELETES the command
            # before acting on it, so its absence is a delivery receipt: gone
            # means a machine read the request, still there means none ever did.
            # The bridge keeps the commandId now and spends it.
            return _emit(body, args.json,
                         _bundle_waiting_lines(want, body))
        status = str(row.get("status") or "")
        if status == "failed":
            return _emit(body, args.json,
                         [f"✗ {want} didn’t send: {_send_logs_failure(row.get('errorClass'))}."], 1)
        if status == "done":
            lines = [f"✓ {want} was sent — {int(row.get('runCount') or 0)} run(s), "
                     f"{_size_words(row.get('sizeBytes'))}."]
            # ⛔ `--runs 0` MEANS THE SAME THING HERE. It is accepted on the send
            # and was dropped in silence on the one call that actually uploads —
            # so an assistant carrying the person's own words forward got nothing
            # and was told nothing. Only the `0` is read: this bundle has already
            # been built, so a RUN named here would change nothing, and that is
            # said rather than ignored.
            _st_spec = [t.strip() for t in
                        str(getattr(args, "runs", "") or "").replace(" ", ",").split(",")
                        if t.strip()]
            _st_wants_log = _AGENT_LOG_TOKEN in _st_spec
            _st_other = [t for t in _st_spec if t != _AGENT_LOG_TOKEN]
            if _st_other:
                lines.append("(Only 0 — the agent’s own log — means anything on a "
                             "check; that bundle is already built, so naming runs "
                             "here changes nothing.)")
            if getattr(args, "agent_log", False) or _st_wants_log:
                # ⭐ THE SECOND STEP, AND THE ONLY PLACE IT CAN HAPPEN IN THIS
                # CLIENT. The bundle has landed, so the row now names a folder the
                # app's Clear-logs will list — which is exactly the condition the
                # bridge refuses this without.
                # ⛔⛔ AND THE FACTS COME WITH IT. The consent screen for this file
                # is printed by a DIFFERENT command, and nothing here checks that
                # it ever was — so an assistant arriving straight at this step with
                # a code and a flag could upload it having shown the person
                # nothing. The three sentences are cheap; they ride the flag.
                #
                # ⚠ THEY ARE BUFFERED, NOT PRINTED, AND THAT IS THIS CLIENT'S
                # SHAPE RATHER THAN AN OVERSIGHT. Every command here emits ONE
                # message at the end, so the bytes are gone before any of it
                # renders — but the person reads the facts ABOVE the result, which
                # is the order that matters to them. The terminal, which prints as
                # it goes, prints them before the call.
                lines.extend(_agent_log_facts())
                ac, ab = _post("/logs/agent-log", {"code": want})
                if ac != 200:
                    lines.append("The agent’s own log did not go: "
                                 f"{ab.get('error', ac)}. The rest is unaffected.")
                elif not ab.get("sent"):
                    lines.append("The agent’s log on this host was empty — nothing "
                                 "to add.")
                else:
                    lines.append("The agent’s log on this host went up too.")
            lines.append(f"Quote {want} when you report the problem.")
            return _emit(body, args.json, lines)
        return _emit(body, args.json, [f"{want} is still being packaged."])

    # ⛔⛔ BEFORE THE RUN LIST, AND THAT IS THE WHOLE POINT. `/logs/runs` resolves a
    # selected computer and refuses with "pick a computer" when there is none — so
    # asking it first would make the one request that needs no machine impossible
    # for exactly the people who need it. See `_agent_log_only_request`.
    if _agent_log_only_request(args):
        owned_hint, hint_name = _agent_log_machine_hint(args)
        return _send_agent_log_alone(args, offer_machine=owned_hint, name=hint_name)

    # ⭐⭐ THE LOCAL HALF GOES FIRST, AND IT GOES ALONE. Above `/logs/runs`, above
    # `/logs/send`, above every early return between here and the machine —
    # because each one of those is a state in which the old code lost this file
    # entirely. `/logs/runs` refuses with `no_selection` / `stale_selection` /
    # `no_devices`; `/logs/send` answers 502 when Firestore is the broken thing,
    # which is one of the states people send agent logs ABOUT. After this, the
    # agent's own log survives a dead Firestore, a stalled machine, a selection
    # that went stale and an account with no research computer at all.
    #
    # ⛔ ONLY ON `--confirm`, so nothing leaves without the plan. And only on the
    # COMBINED shape: the log-only request returned two lines up, through the
    # command that exists for it.
    agent_log_code, agent_log_lines = "", []
    if getattr(args, "confirm", False) and _wants_agent_log(args):
        agent_log_code, agent_log_lines = _send_agent_log_now(args)

    def _say(payload: dict, said: "list[str]", rc: int = 0) -> int:
        """⛔ EVERY EXIT FROM HERE OWES THE AGENT-LOG RECEIPT. The upload has
        already happened by the time any of them runs, so a branch that reports
        only its own failure would leave a person who was told "yes" holding no
        record of a file that went."""
        return _emit(payload, args.json, [*agent_log_lines, *said], rc)

    path = "/logs/runs"
    device_arg = getattr(args, "device", "") or ""
    if device_arg:
        dev, fail = _resolve_device_arg(device_arg)
        if dev is None:
            return _say({}, fail, 1)
        path += f"?deviceId={dev.get('id')}"
    code, body = _get(path)
    if code != 200:
        if body.get("reason") in ("no_selection", "stale_selection", "no_devices",
                                  "selection_not_ready"):
            lines = _pick_device_lines(body, body.get("reason", ""))
            # ⛔⛔ THE ONE THING THIS PERSON CAN ACTUALLY SEND, SAID HERE. With no
            # computer there is no bundle and every sentence above is about picking
            # one — so somebody whose problem IS that they have no computer was
            # handed a screen with no door in it. The agent's own log needs no
            # machine and now carries its own support code.
            if body.get("reason") == "no_devices":
                lines.append("If what’s wrong is this agent itself, I can send its "
                             "own log on its own — no computer needed, and it "
                             "comes back with a support code. Just ask.")
            return _say(body, lines, _fail_code(code))
        return _say(body, [f"✗ {body.get('error', code)}"], _fail_code(code))

    rows = body.get("runs") or []
    # ⛔⛔ THE MACHINE THE LIST CAME FROM, CARRIED ONTO THE SEND. Showing and
    # sending are two separate calls, and with no deviceId the bridge picks the
    # selected machine each time — so a selection that changes in between would
    # show one computer's runs and send from another. The person agreed to what
    # they were shown.
    device_id = str(body.get("deviceId") or "")
    name = body.get("deviceName") or "your Research Computer"
    owned = bool(body.get("owned"))
    machine = bool(getattr(args, "machine", False))
    agent_log = bool(getattr(args, "agent_log", False))

    if machine and not owned:
        # Said here rather than after a round trip. The computer would refuse
        # this anyway; what this decides is whether the person is TOLD, and on
        # a shared computer that is the ordinary case rather than the odd one.
        return _say(body, [
            f"“{name}”’s own logs belong to whoever owns it, so I can’t include "
            "them. Ask again without them and you’ll still get every run of "
            "yours it’s holding."], 1)

    names = [r.get("name") for r in rows]
    if getattr(args, "runs", ""):
        chosen, picked_agent_log, refusal = _resolve_log_selection(rows, args.runs)
        if refusal:
            return _say(body, refusal, 1)
        names = chosen
        # ⛔ EITHER ROUTE, NEVER ONE OVERRIDING THE OTHER — the same rule the
        # terminal follows. `--agent-log` and `--runs 0` say the same thing, and a
        # person who says both must not be answered "no" by whichever the code
        # happened to read second.
        agent_log = agent_log or picked_agent_log
    if getattr(args, "none", False):
        # ⛔ STILL LAST, so it still wins. It is the documented pairing for
        # `--machine` and it means what it has always meant: no runs. It does NOT
        # clear the agent's log, which is not a run and not on that computer.
        names = []
    if not names and not machine:
        # ⛔⛔ IT USED TO BE REFUSED HERE, AND WAVE 8 TURNED THAT INTO A SEND. The
        # old sentence — "can only go up beside a bundle from that computer" — was
        # true of the transport and useless to the reader: this branch is reached
        # when that computer is holding nothing of theirs, which is one of the two
        # states in which no bundle can be built at all. The log now has a route of
        # its own and a support code of its own, so the thing they asked for
        # happens instead of being explained away.
        if agent_log:
            # ⛔⛔ ON A CONFIRM IT HAS ALREADY GONE, AND CALLING THE STANDALONE
            # COMMAND AGAIN WOULD UPLOAD IT TWICE. A live defect created by moving
            # the upload up front, caught by walking every exit between the upload
            # and the machine request rather than by a test. This branch is reached
            # when the machine turns out to be holding nothing, and it used to be
            # the ONLY way the log could go from here — so it sent it. Now the send
            # happened before the run list was ever fetched, and a second call here
            # would mint a second row, store a second copy of a file carrying a
            # masked email and the host's whole sign-in trail, and spend another of
            # the account's ten uploads an hour.
            if getattr(args, "confirm", False):
                return _say(body, [
                    f"“{name}” isn’t holding logs for any of your runs, so there "
                    "was no bundle to ask it for."])
            # ⛔ THE PLAN BRANCH IS UNCHANGED AND MUST BE: nothing has been sent
            # yet, and this is the command that prints the standalone plan.
            # ⛔ THE MACHINE OFFER SURVIVES, AND STILL ONLY FOR AN OWNER — a
            # non-owner is refused `--machine` a few lines above, so offering it to
            # them would send them round the circle a previous wave closed.
            return _send_agent_log_alone(args, offer_machine=owned, name=name)
        if not body.get("published"):
            # ⛔⛔ NOT "it isn't holding any of your runs". The list is absent,
            # which means we cannot see it — a computer that hasn't published
            # one yet, or one on an older build. The other sentence tells
            # somebody their logs are gone while that machine may hold them all.
            return _say(body, [
                f"“{name}” hasn’t told me which runs it’s still holding, so I "
                "can’t offer you a list yet."] + ([
                    "If you own it, I can still send the computer’s own logs — "
                    "that’s the right choice when the problem is with connecting "
                    "it at all."] if owned else []), 1)
        return _say(body, [
            f"“{name}” isn’t holding logs for any of your runs."] + ([
                "If the problem is with connecting it at all, I can send the "
                "computer’s own logs instead — just ask."] if owned else []), 1)

    total = sum(int(r.get("sizeBytes") or 0) for r in rows if r.get("name") in names)

    if not getattr(args, "confirm", False):
        # ⭐⭐ THE HEADER NAMES NO COMPUTER, BECAUSE ROW 0 IS NOT ON ONE. It used
        # to read "… the logs from “{name}”:" and scope the whole list to the
        # research computer, which was true only while row 0 printed LAST, far
        # enough down to read as an aside. Row 0 now leads (see below), so that
        # header would put a file living on THIS host directly under a line
        # naming a different machine — the exact confusion cli.py:2688 says
        # `_print_agent_log_choice` exists as a separate function to avoid. The
        # scope moved down to where it is actually true: `From “{name}”:`.
        lines = ["I can send Super Research support:"]
        # ⛔⛔ EVERY ROW, NUMBERED, AND MARKED GOING OR NOT — not only the ones
        # going. Before this the plan listed the selection and nothing else, which
        # was honest while the selection was always everything; the moment a
        # subset became expressible, a list of only what is going stopped being a
        # list somebody could pick FROM. The numbers are the whole point: they are
        # what a person says back, and a run that is not on screen cannot be asked
        # for. What is going is still unambiguous — the marker carries it, and the
        # count below repeats it in words.
        # ⛔ THE 0 ROW PRINTS EITHER WAY, so the choice exists for somebody who
        # does not already know it does. `--agent-log` shipped in 2026-08-26 and
        # has been reachable only by naming it.
        # ⛔ "MAY NOT BE", NOT "IS NOT" — the terminal's twin. The recommended
        # install co-locates the agent and the backend, so asserting the two
        # differ is false for most people reading it.
        #
        # ⭐⭐ AND IT LEADS, SO READING ORDER MATCHES NUMBERING ORDER. It printed
        # LAST, after runs 1..N, which handed a relay a list that counts DOWN —
        # and a relay will not show a person 1, 2, 0. On 2026-09-20 one renumbered
        # into its own "1."/"2.", the person answered in the RELAY's numbers, and
        # those are not this command's numbers. With one run that happened to
        # refuse loudly; with two it would have sent the wrong run's results,
        # links and account email to support, under a `consent: true` the person
        # gave for a different row.
        lines.append(f"  Run 0 {'•' if agent_log else '·'} the log from the agent on "
                     "THIS host — the machine running this chat, which may not "
                     "be that computer"
                     f"{'' if agent_log else '   (not picked)'}")
        # ⛔ THE SCOPE LINE. Everything below it is on the research computer;
        # everything above it is not. Row 0 is the only thing above it.
        #
        # ⭐⭐ AND IT SAYS WHETHER THAT COMPUTER IS ANSWERING. `/logs/runs` has
        # always returned `online` and this client has always dropped it. The
        # machine is what zips and uploads the bundle — the app only mints the
        # code — so a machine that is not answering produces a support code that
        # names nothing, forever, with no error anywhere. That is exactly what
        # happened on 2026-09-20: four status checks over seventeen minutes, each
        # answered "nothing has come back yet", while the one fact that explained
        # it was on the wire the whole time and never printed.
        #
        # ⛔ "ISN'T ANSWERING", NEVER "IS OFF". This is heartbeat freshness, not
        # truth — a machine that is up with a briefly late heartbeat reads the
        # same. The line never REFUSES on this basis; it only says it, and points
        # at the row that still works without any machine at all.
        online = body.get("online")
        lines.append(f"From “{name}”:" if online is not False
                     else f"From “{name}” — which isn’t answering right now, so "
                          "anything picked below may sit unsent until it is:")
        # ⭐⭐ "Run N", NOT A BARE DIGIT — THE NUMBER RIDES INSIDE THE TEXT. A bare
        # leading "1" is positional, so a relay that re-wraps the rows into its own
        # ordered list produces a SECOND numbering with equal authority and the two
        # silently disagree. A label the client supplies cannot be re-wrapped away:
        # the relay's own index becomes visibly redundant beside it rather than
        # competing with it. This is not a guess — in the 2026-09-20 transcript the
        # assistant INVENTED exactly these labels ("Run 1", "Run 0") and mapped them
        # correctly while getting the order wrong, so the label is the part that
        # already survives. Zero resolver cost: `_SPOKEN_FILLER` already drops
        # "run"/"runs"/"number", so "run 1 and run 0" has always resolved.
        for i, row in enumerate(rows, 1):
            going = row.get("name") in names
            # ⛔ THE RUN'S OWN STATUS IS ON THE ROW. cli.py's `_print_held_runs`
            # has always printed it and this client dropped it, so the chat plan
            # offered "Managed Creative Cycles — 37.8 KB" for a run that had
            # STOPPED in phase 3 without saying so. A failed run's bundle is
            # perfectly sendable — the folder is on the disk and the machine
            # published its size — but somebody deciding what to send support is
            # choosing between runs, and which one broke is the thing they are
            # choosing on.
            status = str(row.get("status") or "").strip()
            lines.append(f"  Run {i} {'•' if going else '·'} {_log_run_label(row)} — "
                         f"{_size_words(row.get('sizeBytes'))}"
                         f"{f' · {status}' if status else ''}"
                         f"{'' if going else '   (not picked)'}")
        if body.get("truncated"):
            lines.append("  (only the most recent are listed — it’s holding more)")
        if machine:
            lines.append("Plus that computer’s own logs: its pairing and sign-in "
                         "records and its raw activity trail, which cover every "
                         "run it has ever done, for everyone who uses it.")
        else:
            lines.append("That computer’s own logs are not included.")
        # ⛔⛔ A DIFFERENT COMPUTER. Everything else in this plan describes material
        # leaving the RESEARCH computer; the agent's log is on the host running the
        # bridge, and in a chat setup that is very often somewhere else entirely.
        # Kept as its own sentence rather than folded into the list below, for the
        # same structural reason the app keeps retention out of `consentIncluded`.
        if agent_log:
            lines.append("Plus the log from the agent on the host running this — a "
                         "connection and sign-in record, not research content.")
            # ⛔⛔ ONE SOURCE WITH THE STANDALONE PLAN. These three sentences are
            # printed from two places in this file now, and a guard compares the
            # claims against the terminal's twin — a second hand-written copy is
            # how one of them quietly stops being said on one of the paths.
            lines.extend(_agent_log_facts())
        else:
            lines.append("The agent’s own log is not included.")
        # ⛔⛔ The three facts the app's modal names and this plan did not — see
        # the note beside the same lines in cli.py. Only topics and titles were
        # conveyed, by the run list itself.
        lines.append("Also going, from the runs picked: links that open those "
                     "results — anyone holding one can read them; the email "
                     "address on the account; and what the agent screens showed "
                     "while those runs were working.")
        # ✅ THE RETENTION LINE ARRIVED 2026-08-26, WITH THE RULE — see the
        # longer note beside the same line in cli.py.
        #
        # ⚠ NOT byte-identical to cli.py's, and that is deliberate rather than
        # drift: this file speaks in contractions and curly punctuation
        # throughout ("It’s", "That’s") and cli.py does not, so matching it
        # character for character would put a foreign sentence in the middle of
        # this plan. What must NOT differ is the FACT — the same number, the same
        # clock, the same subject — because a person who asks two clients how
        # long their logs are kept must not get two answers. The guard therefore
        # compares the claim, not the string.
        lines.append("It’s deleted automatically 30 days after it arrives.")
        lines.append(f"That’s {len(names)} run(s), about {_size_words(total)}. "
                     "Only Super Research support can read them.")
        # ⛔ THE NUMBERS ARE USELESS WITHOUT THIS LINE. The rows carry indices now,
        # and nothing else in the conversation tells a person — or the assistant
        # relaying for them — that saying a number is a thing they may do.
        # ⚠ NO POSITIONAL CLAIM ("the numbers on the left") — a position stops
        # being true the moment anything re-wraps the rows, which is the exact
        # failure this sentence has to survive. The row LABEL is the handle.
        lines.append("Say yes and I’ll send them — or say which numbers to send "
                     "instead (0 is the agent’s own log).")
        # ⛔⛔ THE NUMBERS ARE POSITIONS IN THE LIST ABOVE, AND THE CONFIRM IS A
        # SECOND PROCESS. It re-fetches `/logs/runs`, which re-resolves the
        # selected device and re-reads a list the machine republishes as runs
        # start, finish and age out — so between the plan and the send, position
        # 2 can become a different run, or a different computer's run. Nothing
        # carried identity across the two calls.
        #
        # ⛔ SO THE DIRECTIVE HANDS BACK NAMES AND THE DEVICE, not numbers. Names
        # are what the machine matches on and what the bridge validates; the
        # deviceId pins the computer the person was actually shown. The numbers
        # stay in the words, because that is what a person says.
        confirm = ["send-logs", "--confirm", f"--device {device_id}"]
        if names:
            confirm.append("--runs " + ",".join(names))
        elif not machine:
            confirm.append("--none")
        if machine:
            confirm.append("--machine")
        if agent_log:
            confirm.append("--agent-log")
        directives = [
            "If they say yes to exactly what is listed above, run: sr.py "
            + " ".join(confirm),
            "⛔ Those are RUN NAMES and a device id, not the numbers shown — the "
            "numbers are positions in a list this command re-fetches, and it can "
            "have changed by then.",
            "If they ask for a different set, re-run the bare command first and "
            "show them the new plan; never edit this line by hand.",
            # ⭐⭐ THE RELAY RULE ARRIVES WITH THE BYTES IT GOVERNS. SKILL.md states
            # "relay verbatim" TWELVE times, once in bold and output-specific to
            # this very plan — and on 2026-09-20 the plan was still reflowed into
            # a Markdown list under a second set of numbers. Prose in a file three
            # hundred lines away is measured-failed; the two relay rules in this
            # skill that have NEVER failed (`_AGENT_ONLY_MARKER` and the `MEDIA:`
            # line) are both carried IN BAND, attached to the message they govern.
            # So is this one.
            # ⛔ LAST, NOT FIRST. The action directive above is what the assistant
            # must DO; a formatting rule placed before it pushes the thing that
            # matters into second position.
            "⛔ Relay the rows above exactly as printed, each on its own line, "
            "keeping the “Run N” labels. Do NOT re-number them into a list of "
            "your own — the user answers in the numbers they can see, and yours "
            "are not this command’s.",
        ]
        return _emit({**body, "wouldSend": names, "includeMachine": machine},
                     args.json, [*lines, *_agent_directive_block(directives)])

    payload = {"runNames": names, "includeMachine": machine,
               # ⛔ Set on this branch ONLY. It claims the person was shown what
               # leaves their computer, and the branch above is where that
               # happened. Moving it up would make the claim false.
               "consent": True,
               # ⭐⭐ THE SECOND CODE IS RE-DERIVABLE FROM THE FIRST. The local
               # half has already gone under its own code by the time this runs,
               # and two bare codes in a chat message is how somebody quotes the
               # wrong one at support. Handing it over here lets the bridge
               # remember the pair, so `--status <bundle code>` can always say
               # "the agent's log already went as <other>" — which is also what
               # stops a later branch offering to send the same file again.
               "agentLogCode": agent_log_code,
               # ⭐ THE CHAT THAT IS WAITING. The machine packages and uploads the
               # bundle itself, so the only honest thing this command can say is
               # "asked" — whether it ARRIVED was reachable only by somebody
               # thinking to ask again. With an origin the watchdog can say so
               # unprompted, in the chat that made the request.
               "origin": _origin_from_env() or None,
               # Always the machine the list came from — see above.
               "deviceId": device_id}
    code, sent = _post("/logs/send", payload)
    if code != 200:
        return _emit(sent, args.json,
                     [f"✗ couldn’t send the logs: {sent.get('error', code)}"], _fail_code(code))
    support = sent.get("code", "")
    lines = [
        f"✓ Asked “{name}” for the logs. Your support code is {support}.",
        "It takes a moment to package. Ask me to check on it and I’ll look.",
    ]
    directives = [
        f"To check on it later, run: sr send-logs --status {support}",
        "Do not poll on a timer — only when the user asks.",
    ]
    if agent_log_code:
        # ⛔⛔ IT HAS ALREADY GONE, AND SAYING SO IS WHAT PREVENTS A SECOND COPY.
        # This branch used to read "the agent's own log goes up once that
        # computer's bundle lands" and hand over `--status <CODE> --agent-log`, a
        # step the bridge refuses until the machine's row exists — so when the
        # machine never answered, the local file was lost with it. It is now sent
        # before this function ever reaches the machine.
        #
        # ⛔ TWO CODES, EACH NAMED BY ITS ROLE. Two bare codes in a chat message
        # is how somebody opens the wrong one at support.
        lines.append(f"The agent’s own log went separately, under its own code "
                     f"{agent_log_code} — quote both: {agent_log_code} is this "
                     f"host’s log, {support} is “{name}”’s bundle.")
        directives.append(
            f"⛔ The agent’s log is ALREADY SENT, as {agent_log_code}. Do NOT run "
            f"`--status {support} --agent-log` — that would upload the same file "
            "a second time under the other code, and spend one of the account’s "
            "ten uploads an hour on a duplicate.")
        directives.append(
            f"Quote BOTH codes whenever you mention either: {agent_log_code} = "
            f"the agent’s own log (sent), {support} = the bundle from “{name}” "
            "(requested).")
    elif agent_log:
        # ⛔ THE UPLOAD WAS ATTEMPTED AND DID NOT PRODUCE A CODE — it failed, or
        # the log was empty. `agent_log_lines` already said which, in the person's
        # words, above; what is owed here is the way to try again, because the
        # attempt is not repeated automatically.
        directives.append(
            "The agent’s own log did NOT go (the line above says why). To try it "
            "on its own: sr send-logs --confirm --agent-log --none")
    return _emit({**sent, "agentLogCode": agent_log_code}, args.json,
                 [*agent_log_lines, *lines, *_agent_directive_block(directives)])


def cmd_list(args) -> int:
    """List the account's recent researches (newest first), so the user can ask for
    any one's links or podcast BY NAME. Account-wide — EVERY research, not just the
    agent-started ones (that's `updates`, the active-only streaming view). The
    per-run links/podcast are then fetched on demand via `status` / `podcast`,
    which already resolve any of these by title."""
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    if not runs:
        return _emit(body, args.json,
                     ["You don't have any researches yet — just name a topic to start one."])
    lines = ["Your researches (newest first):"]
    for r in runs:
        title = r.get("title") or r.get("topic") or r.get("runId")
        lines.append(f"  • “{title}” — {r.get('status', '?')}")
    lines.append("Ask for any one’s results, a specific link (brief / a report / podcast), or its podcast.")
    return _emit(body, args.json, lines)


def cmd_stop(args) -> int:
    """Graceful stop (the chat /sr stop) — keeps the results so far + the chat."""
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    unsure = None if args.runId else _refuse_to_guess(body, "stop")
    if unsure:
        return _emit(unsure[0], args.json, unsure[1], 1)
    run = _pick_run(runs, args.runId, prefer_active=True)
    if run is None:
        which = f"matching “{args.runId}”" if args.runId else "to stop"
        return _emit(body, args.json, [f"No run {which}."], 1)
    rid = run.get("runId")
    title = run.get("title") or run.get("topic") or rid
    code, b2 = _post(f"/research/{urllib.parse.quote(rid, safe='')}/stop")
    if code != 200:
        return _emit(b2, args.json, [f"✗ stop failed: {b2.get('error', code)}"], _fail_code(code))
    if b2.get("alreadyDone"):
        return _emit(b2, args.json, [f"“{title}” already finished ({b2.get('status')}) — nothing to stop."])
    return _emit(b2, args.json, [
        f"✓ Stopped “{title}”.",
        "Your results so far are kept.",
    ])


def cmd_pause(args) -> int:
    """Pause a running run — it stays RESUMABLE (unlike stop, which ends it)."""
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    unsure = None if args.runId else _refuse_to_guess(body, "pause")
    if unsure:
        return _emit(unsure[0], args.json, unsure[1], 1)
    run = _pick_run(runs, args.runId, prefer_active=True)
    if run is None:
        which = f"matching “{args.runId}”" if args.runId else "to pause"
        return _emit(body, args.json, [f"No run {which}."], 1)
    rid = run.get("runId")
    title = run.get("title") or run.get("topic") or rid
    code, b2 = _post(f"/research/{urllib.parse.quote(rid, safe='')}/pause")
    if code != 200:
        return _emit(b2, args.json, [f"✗ couldn't pause: {b2.get('error', code)}"], _fail_code(code))
    return _emit(b2, args.json, [
        f"⏸ Paused “{title}”.",
        "Tell me to resume it whenever you’re ready.",
    ])


def cmd_resume(args) -> int:
    """Resume a paused run."""
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    unsure = None if args.runId else _refuse_to_guess(body, "resume")
    if unsure:
        return _emit(unsure[0], args.json, unsure[1], 1)
    # Prefer a PAUSED run (that's what resume targets) before the generic newest pick,
    # so a bare "resume" doesn't grab a newer ongoing/terminal run.
    paused = [r for r in runs if (r.get("status") or "") == "paused"]
    run = _pick_run(paused or runs, args.runId, prefer_active=True)
    if run is None:
        which = f"matching “{args.runId}”" if args.runId else "to resume"
        return _emit(body, args.json, [f"No run {which}."], 1)
    rid = run.get("runId")
    title = run.get("title") or run.get("topic") or rid
    code, b2 = _post(f"/research/{urllib.parse.quote(rid, safe='')}/resume")
    if code != 200:
        return _emit(b2, args.json, [f"✗ couldn't resume: {b2.get('error', code)}"], _fail_code(code))
    return _emit(b2, args.json, [f"▶ Resumed “{title}”."])


def cmd_retry(args) -> int:
    """Resume a run that's waiting on a decision / hit an error (C1)."""
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    unsure = None if args.runId else _refuse_to_guess(body, "retry")
    if unsure:
        return _emit(unsure[0], args.json, unsure[1], 1)
    run = _pick_run(runs, args.runId, prefer_active=True)
    if run is None:
        which = f"matching “{args.runId}”" if args.runId else "to retry"
        return _emit(body, args.json, [f"No run {which}."], 1)
    rid = run.get("runId")
    title = run.get("title") or run.get("topic") or rid
    refusal = _refuse_if_not_offered(run, "retry")
    if refusal:
        return _emit(body, args.json, refusal, 1)
    code, b2 = _post(f"/research/{urllib.parse.quote(rid, safe='')}/resolve", {"intent": "retry"})
    if code != 200:
        return _emit(b2, args.json, [f"✗ couldn’t retry “{title}”: {b2.get('error', code)}"], _fail_code(code))
    # ⛔ Say what actually happened. A checkpoint resume is a REQUEST to the
    # research computer — it re-enqueues from disk, and it can still decline
    # (artifacts pruned, run marked stopped) without telling us. Claiming "the
    # run is resuming" was the lie this whole item exists to stop.
    if b2.get("transport") == "queue_resume":
        return _emit(b2, args.json,
                     [f"↻ Asked your computer to pick “{title}” up from its last checkpoint."])
    return _emit(b2, args.json, [f"↻ Retrying “{title}” — resuming the run."])


_SKIP_NAMES = {"brief": 1, "podcast": 3, "audio": 3, "video": 4, "youtube": 4, "report": 5, "email": 5}

# P2 agents skippable BY NAME — parity with the web app's per-agent Research
# toggles ("skip Claude in P2" was un-doable from chat, live 2026-07-02).
_SKIP_AGENTS = {"chatgpt": "chatgpt", "gpt": "chatgpt", "openai": "chatgpt",
                "claude": "claude", "anthropic": "claude", "gemini": "gemini"}
_AGENT_DISPLAY = {"chatgpt": "ChatGPT", "gemini": "Gemini", "claude": "Claude"}


def cmd_skip(args) -> int:
    code, body, runs = _fetch_runs(limit=_LOOKUP_LIMIT)
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    # ⛔ Bare means no run NAMED — phases or not. `skip video` with no `--run`
    # reconfigures whichever run it picks, so it asks exactly as `skip` does.
    unsure = None if args.run else _refuse_to_guess(body, "skip")
    if unsure:
        return _emit(unsure[0], args.json, unsure[1], 1)
    run = _pick_run(runs, args.run or None, prefer_active=True)
    if run is None:
        which = f"matching “{args.run}”" if args.run else "to skip in"
        return _emit(body, args.json, [f"No run {which}."], 1)
    rid = run.get("runId")
    title = run.get("title") or run.get("topic") or rid
    q = urllib.parse.quote(rid, safe="")
    if not args.phases:
        # No phases → skip whatever the run is BLOCKED on (resolve the decision).
        # ⛔ Not every card HAS a skip. On the browser-launch failure card the
        # command chat used to mint here terminated the run outright, while this
        # printed "Skipping the current blocker".
        refusal = _refuse_if_not_offered(run, "skip")
        if refusal:
            return _emit(body, args.json, refusal, 1)
        code, b2 = _post(f"/research/{q}/resolve", {"intent": "skip"})
        if code != 200:
            return _emit(b2, args.json,
                         [f"✗ couldn’t skip the blocker on “{title}”: {b2.get('error', code)}"],
                         _fail_code(code))
        if b2.get("action") == "discard":
            return _emit(b2, args.json, [f"✓ Put that card away — “{title}” stays stopped."])
        return _emit(b2, args.json, [f"⏭ Skipping the current blocker on “{title}”."])
    # Phases and/or P2 agents given → tune the run's config (skip whole phases
    # when reached; turn named agents off — the app's per-agent toggle write).
    phases = []
    agents = []
    # ⛔⛔ THE REFUSAL NAMES EVERYTHING THIS COMMAND ACCEPTS, AND IT IS DERIVED.
    # Hand-written it listed four of the seven phase words and three of the six
    # agent words, so `audio`, `youtube`, `openai` and `anthropic` all WORKED and
    # the error message said they did not.
    _accepted = (f"{'/'.join(str(n) for n in _SKIP_PHASE_NUMBERS)}, "
                 f"{'/'.join(_SKIP_NAMES)}, or a Research agent: "
                 f"{'/'.join(_SKIP_AGENTS)}")
    for p in args.phases:
        lp = p.lower()
        if p.isdigit():
            # ⛔ ANY INTEGER PARSED AND POSTED — `sr skip 0`, `sr skip 2` (the
            # Research stage, which is not skippable) and `sr skip 99` all reached
            # the backend. The router cannot produce one, the CLI could.
            if int(p) not in _SKIP_PHASE_NUMBERS:
                return _emit({}, args.json,
                             [f"✗ phase {int(p)} isn’t one I can skip ({_accepted})"], 1)
            phases.append(int(p))
        elif lp in _SKIP_NAMES:
            phases.append(_SKIP_NAMES[lp])
        elif lp in _SKIP_AGENTS:
            agents.append(_SKIP_AGENTS[lp])
        else:
            return _emit({}, args.json,
                         [f"✗ unknown phase '{p}' ({_accepted})"], 1)
    payload: dict = {}
    if phases:
        payload["phases"] = sorted(set(phases))
    if agents:
        payload["agents"] = sorted(set(agents))
    code, b2 = _post(f"/research/{q}/skip", payload)
    if code != 200:
        return _emit(b2, args.json, [f"✗ skip failed: {b2.get('error', code)}"], _fail_code(code))
    parts = []
    if b2.get("skipped"):
        parts.append(f"phase(s) {b2.get('skipped')}")
    if b2.get("agentsOff"):
        parts.append(" + ".join(_AGENT_DISPLAY.get(a, a) for a in b2["agentsOff"])
                     + " in Research (P2)")
    what = " and ".join(parts) or "that"
    # commandSent = the run is ongoing and the mid-run config command landed —
    # the change applies NOW, not just at the next phase boundary.
    tail = " — applied to the running pipeline too." if b2.get("commandSent") else " when reached."
    return _emit(b2, args.json, [f"✓ Will skip {what} of “{title}”{tail}"])


def cmd_logout(args) -> int:
    # Capture WHO we're logging out first (the /logout response only returns ok),
    # so we can name the account in the confirmation.
    who = ""
    try:
        sc, sb = _get("/status")
        if sc == 200 and sb.get("authed"):
            who = sb.get("email") or sb.get("uid") or ""
    except Exception:
        pass
    code, body = _post("/logout")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    msg = f"✓ Logged out of {who}." if who else "✓ Logged out — account session cleared."
    return _emit(body, args.json, [msg])


def cmd_version(args) -> int:
    """Show the Super Research skill's version (+ a "newer available" nudge for
    the SKILL when one is published). SKILL-ONLY (2026-07-06, user): the backend
    line ("Backend: not installed on the connected device" — the runtime host,
    not the Research computer) only confused; the backend's version lives in the
    app's Settings → About and `superresearch --version` on the Research
    computer."""
    # Explicit ask ⇒ FRESH PyPI read (2026-07-06, user: "any update found?"
    # right after a publish must see it — a stale 24h-cached "no" is a lie).
    code, body = _get("/version?fresh=1")
    if code != 200:
        return _emit(body, args.json, [f"✗ couldn't read versions: {body.get('error', code)}"],
                     _fail_code(code))
    agent = body.get("agent") or "?"
    a_new = body.get("agentLatest")
    lines = [f"Super Research skill  v{agent}"
             + (f"   ⬆️ v{a_new} available — say “update”" if a_new else "")]
    # Stale chat-side copy tell: the runtime executes its own installed COPY of
    # these scripts, which only `connect` / “update” redeploys — a host pip
    # upgrade alone leaves the chat side on old behavior (live 2026-07-02: a
    # stale copy predated the podcast MEDIA: fix). Name it.
    if agent not in ("?", _SKILL_BUILD):
        lines.append(f"⚠ This chat's scripts are v{_SKILL_BUILD} but the skill is v{agent} — "
                     "say “update” to redeploy them.")
    return _emit(body, args.json, lines)


def cmd_update(args) -> int:
    """Update the Super Research SKILL — this chat runtime (its /sr scripts +
    bridge) — to the latest published version (the bridge reconnects from the
    latest in the background). The skill is the ONLY thing this updates; backend
    updates are done in the app / with `superresearch --update` on the host."""
    code, body = _post("/agent-install")
    if code != 200:
        err = body.get("error", "")
        if err == "agent_unavailable":
            msg = ("can't reach the latest skill right now — the device may be offline, "
                   "or this version isn't published yet. (Nothing changed; the skill is still running.)")
        elif err == "update_helper_failed":
            msg = "couldn't start the update (is pipx available on the connected device?)"
        else:
            msg = f"couldn't start the update: {err or code}"
        return _emit(body, args.json, [f"✗ {msg}"], _fail_code(code))
    if body.get("already"):
        cur = body.get("current") or ""
        return _emit(body, args.json,
                     [f"✓ The skill is already up to date{(' (v' + cur + ')') if cur else ''}."])
    # Seamless finish: the bridge restarts on the new version in the background;
    # hand the assistant a DETERMINISTIC verify→reload→confirm script so it doesn't
    # improvise multi-step recovery (the reported friction) and the user gets ONE
    # clean confirmation. The reload step runs the runtime's OWN skill-reload (Hermes
    # /reload-skills) — the one thing the skill can't self-trigger — so it cooperates
    # with the runtime instead of fighting it.
    finish = [
        "The Super Research update is now running: a detached helper is upgrading the "
        "package and restarting the bridge on the new version. Finish it cleanly, in "
        "THIS order — act SILENTLY, do not narrate these steps:",
        "1. Wait ~30 seconds for the new bridge to come up (the package upgrade can "
        "briefly leave the bridge unreachable — that's expected).",
        "2. Run the Super Research `version` command. If it errors (bridge still "
        "restarting / unreachable) or still reports the OLD version, wait ~15s and "
        "retry — up to 6 times (~90s total) before giving up.",
        "3. Once `version` reports the NEW version, run your runtime's skill-reload "
        "command ONCE (Hermes: /reload-skills) so the refreshed /sr scripts are picked "
        "up. Skip this if your runtime has no reload command. NOTE: before the reload, "
        "`version` may warn that “this chat's scripts are older” — that is EXPECTED and "
        "the reload fixes it; do NOT run “update” again (no update loop).",
        "4. Then post ONE line to the user: “✓ Super Research updated to v<version> and "
        "reloaded.” If after the retries it still shows the old version, tell the user "
        "the update didn’t take and to say “update” again.",
    ]
    return _emit(body, args.json,
                 ["⬆️ Updating Super Research to the latest version — the bridge restarts on "
                  "the new version in a few seconds. I’ll confirm here once it’s live."]
                 + _agent_directive_block(finish))


def cmd_install(args) -> int:
    """Install the Super Research BACKEND on the connected device — turns that PC
    into a research host (`pipx install superresearch`). The install runs in the
    background; the rest of the setup (ending in the access code) is the install
    page's, done on the host.

    ⭐ ONLY FOR AN EXPLICIT "install it HERE" (owner, 2026-09-24). "Install / set
    up Super Research" on its own is answered with the install page by the router
    — this command installs on the machine the CHAT runs on, which is rarely the
    computer a new person means. So both replies OPEN with the page, and neither
    hands anybody `superresearch --pair`: the page's own pairing step does that,
    per OS, and stays current when it changes."""
    code, body = _post("/install-backend")
    if code != 200:
        err = body.get("error", "")
        if err == "install_helper_failed":
            msg = "couldn't start the install (is pipx available on the connected device?)"
        else:
            msg = f"couldn't start the install: {err or code}"
        return _emit(body, args.json, [f"✗ {msg}"], _fail_code(code))
    if body.get("already"):
        # ⛔ NOT "say “devices” to see/pair it". `devices` lists; it cannot pair
        # anything, so that sent somebody to a command that could not do what it
        # promised. An installed machine that is not on the account yet finishes
        # the page's steps, and those end with the code.
        return _emit(body, args.json, [
            f"The setup steps are at {_INSTALL_PAGE_URL} — Super Research is "
            "already installed on this device.",
            "If it isn’t on your account yet, carry on with that page’s next step "
            "on this device — this device then shows an 8-character access code; "
            "send it to me and I’ll connect it. Say “devices” to see the computers "
            "your account has.",
            "To update it, run “superresearch --update” on that computer or update "
            "it from the app (Settings → About).",
        ])
    return _emit(body, args.json, [
        f"The setup steps are at {_INSTALL_PAGE_URL}.",
        "⬇️ Installing Super Research on this device in the background — that’s "
        "the first of them.",
        "When it finishes, carry on with that page’s next step on this device — "
        "this device then shows an 8-character access code; send it to me and "
        "I’ll connect it.",
        "(Then finish the API-key + browser-login steps on it and it’s ready.)",
    ])


def _stream_arm_directive_lines(script_name: str, job_name: str) -> list[str]:
    """ASSISTANT-ONLY fallback directive: ask the runtime's cronjob tool to arm the
    watchdog. Only used when the deterministic jobs.json write can't run (legacy
    no-origin gateway) or fails (unusual layout / permissions) — the caller wraps
    these under the do-not-relay marker so the user never sees the cronjob syntax."""
    return [
        "Arm this chat's live-progress watchdog NOW with your cronjob tool so run "
        "progress and the 🎉 completion post here on their own:",
        f'  cronjob: create no_agent=true schedule="every 1m" '
        f'script="{script_name}" name="{job_name}"',
        "Create it now. Skip ONLY if your cronjob tool already lists a job with this "
        "exact name (then leave that one — do not duplicate) or if your runtime has "
        "no cronjob tool. Do NOT skip just because no run looks active yet — a "
        "just-started run isn't visible for a few seconds; once armed the watchdog "
        "persists and streams every run until `agent disconnect`.",
        "Arm the once-daily skill-update notice the same way (skip only if a job "
        "named sr-update-notice is already listed):",
        '  cronjob: create no_agent=true schedule="every 1d" '
        'script="sr_update_notice.py" name="sr-update-notice"',
    ]


def _clear_login_wait(slug: str) -> None:
    """Forget how long the PREVIOUS sign-in attempt waited, for this chat.

    ⛔⛔ WITHOUT THIS THE WATCHDOG SELF-DESTRUCTS ON ITS FIRST TICK, FOREVER AFTER.
    `sr_attention_poll._tick_unauthed` counts 401 ticks into `__login_wait__` and
    tears the cron row down once the count passes `_LOGIN_WAIT_LIMIT` — and the
    give-up returns BEFORE the write, so the file is left holding the limit
    permanently. Nothing else ever resets it: arming rewrites the shim and the
    cron row and never touches the state file, and the only other reset is a 200
    tick, which a signed-out chat cannot reach. So one abandoned sign-in poisons
    the chat: every later `login` arms a listener that dies on its first tick, and
    a sign-in completed ninety seconds later announces nothing at all.

    ⭐ ARMING IS THE EVENT "a new sign-in attempt begins for this chat", which is
    exactly the scope `_LOGIN_WAIT_LIMIT`'s own docstring claims to bound ("a
    sign-in that never completes can't poll forever" — ONE sign-in). Resetting
    here restores the meaning the constant already advertises rather than adding
    a new one.

    Best-effort, like everything else in the arm path: a state file we cannot read
    or write is not a reason to refuse to arm. And the run de-dup keys are left
    exactly as they are — dropping those would re-announce every finished run.
    """
    try:
        path = _scripts_dir() / f".sr_poll_{slug}.state.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(raw, dict) or "__login_wait__" not in raw:
        return
    raw.pop("__login_wait__", None)
    try:
        path.write_text(json.dumps(raw), encoding="utf-8")
    except Exception:
        pass


def _prepare_stream_arm() -> tuple[list[str], dict, int]:
    """Arm THIS chat's run-scoped streaming watchdog and return ``(lines, payload,
    rc)``. On the modern path (a chat origin is known) this WRITES the cron job row
    straight into jobs.json (``_arm_stream_cron`` — idempotent, deterministic) and
    returns EMPTY ``lines`` (nothing for the AI to do). ``lines`` are non-empty only
    on the fallback paths: a legacy no-origin gateway, or a failed direct write —
    then they're ASSISTANT-ONLY cronjob directives the caller wraps via
    ``_agent_directive_block``. Writes a shim that bakes in this chat's origin (the
    cron can't take args or read the session env). The watchdog PERSISTS once armed
    (removed only by `agent disconnect`); arming is idempotent, so re-running on every
    research start / login is a safe no-op. A shim-write error → a single ✗ line +
    rc=1 (the caller drops it on the auto-arm paths)."""
    origin = _origin_from_env()
    if origin is None:
        # Legacy gateway with no chat origin: can't write a delivering job (an
        # origin-less job drops / mis-routes), so fall back to the AI cronjob
        # directive for the shared account-wide watchdog.
        payload = {"script": "sr_attention_poll.py", "name": "sr-stream",
                   "schedule": _STREAM_SCHEDULE["display"], "scoped": False,
                   "armed": False}
        return (_stream_arm_directive_lines("sr_attention_poll.py", "sr-stream"),
                payload, 0)
    slug = _origin_slug(origin)
    script_name = f"sr_poll_{slug}.py"
    job_name = f"sr-stream-{slug}"
    _clear_login_wait(slug)
    err = _write_poll_shim(_scripts_dir(), script_name, origin)
    if err:
        return ([f"✗ {err}"], {"error": err}, 1)
    # Deterministic arm: write the cron rows straight into jobs.json. This skill runs
    # in-chat so it has the origin + reach to the cron store — no dependence on the AI
    # calling cronjob:create (the recurring miss). Idempotent by name.
    # ⭐ A minute-anchored cron expression where the runtime can compute one, the
    # interval elsewhere (`_stream_schedule`, owner 2026-09-25).
    schedule = _stream_schedule()
    armed = _arm_stream_cron(script_name, job_name, origin, schedule)
    # The once-daily update notice rides the same deterministic arm (best-effort: its
    # result doesn't gate the fallback below — only the watchdog's does, since a missed
    # update NOTICE is cosmetic while a missed watchdog is the bug we're fixing).
    _arm_stream_cron("sr_update_notice.py", "sr-update-notice", origin,
                     _UPDATE_NOTICE_SCHEDULE)
    # ⛔ The schedule REPORTED is the one written; the fallback directive below
    # asks the AI for the interval, so that is what an unwritten arm reports.
    payload = {"script": script_name, "name": job_name,
               "schedule": (schedule if armed else _STREAM_SCHEDULE)["display"],
               "scoped": True, "origin": origin, "armed": armed}
    if armed:
        return ([], payload, 0)  # armed silently — nothing for the AI to do
    # Couldn't write jobs.json (unusual layout / permissions) → fall back to asking
    # the AI to arm via its cronjob tool (the legacy, less-reliable path).
    return (_stream_arm_directive_lines(script_name, job_name), payload, 0)


def cmd_arm_stream(args) -> int:
    """Arm THIS chat's streaming watchdog. Normally the skill arms it itself (a direct
    jobs.json write); research / login auto-arm the same way. This is the explicit
    standalone form."""
    lines, payload, rc = _prepare_stream_arm()
    if rc == 0 and not lines:
        # Armed deterministically (direct jobs.json write) — nothing for the AI to do.
        lines = ["✓ Live updates are on for this chat — run progress and the "
                 "completion will post here on their own."]
    elif rc == 0:
        lines = _agent_directive_block(lines)
    return _emit(payload, args.json, lines, rc)


# Statuses that mean "the watchdog should be ticking for this run" — mirrors
# sr_attention_poll._LIVE_STUCK (+ ongoing/queued are its _ACTIVE core).
_LIVE_RUN_STATUSES = ("queued", "ongoing", "paused_backend_restart",
                      "paused_backend_restart_failed")
# An armed watchdog rewrites its state file EVERY 1-min tick; older than this
# (or missing) while an agent run is live = the watchdog is NOT ticking.
_STREAM_STALE_SEC = 180


def _stream_health_lines(runs: list) -> list[str]:
    """Deterministic watchdog self-heal. The streaming watchdog — the thing that
    posts '⚠ needs you' / '🎉 done' WITHOUT being asked — is armed by the skill
    writing the cron row into jobs.json (see _prepare_stream_arm); if that job is
    somehow removed out-of-band, the chat goes silent and a blocked run just sits
    until the user happens to ask for status (live 2026-07-02: 'ChatGPT stopped
    responding' surfaced only on a manual ask, ~50 min late). Every armed tick
    rewrites the watchdog's state file, so a missing/stale file while an agent-fired
    run is live == not ticking → re-run the (idempotent) arm right from this
    status/updates reply. Silent on any doubt — never nag a healthy chat.

    Review catch: only counts runs THIS chat's watchdog would actually stream
    (chatOrigin matches this chat — the same platform+chat scope the per-chat
    shim queries with). Without that, a status ask from a DIFFERENT chat would
    arm a scoped watchdog that can never see the run — it posts nothing and,
    per the poll's never-tear-down-on-empty rule, never removes itself."""
    try:
        origin = _origin_from_env()

        def _mine(r: dict) -> bool:
            if not (r.get("viaAgent")
                    and (r.get("status") in _LIVE_RUN_STATUSES or r.get("needsAttention"))):
                return False
            if origin is None:
                return True  # account-wide watchdog streams every agent run
            co = r.get("chatOrigin")
            return (isinstance(co, dict)
                    and (co.get("platform") or "").strip().lower()
                    == (origin.get("platform") or "").strip().lower()
                    and (co.get("chat_id") or "").strip()
                    == (origin.get("chat_id") or "").strip())

        if not any(_mine(r) for r in runs):
            return []
        name = (f".sr_poll_{_origin_slug(origin)}.state.json" if origin
                else ".sr_stream_state.json")
        state = _scripts_dir() / name
        if state.exists() and (time.time() - state.stat().st_mtime) < _STREAM_STALE_SEC:
            return []  # ticking — healthy, say nothing
        # Re-arm deterministically (idempotent — a no-op if the cron is already
        # present). Only the fallback paths return directive lines to relay.
        arm_lines, _payload, rc = _prepare_stream_arm()
        return _agent_directive_block(arm_lines) if (rc == 0 and arm_lines) else []
    except Exception:
        return []


# ── `do` — deterministic natural-language fallback (#891) ───────────────────
# SKILL.md sends any message the AI can't confidently map to a command here
# VERBATIM. The text→command mapping then lives in CODE (ordered, unit-tested
# rules) instead of the chat AI's judgment — the live failures were exactly
# mis-picks ("Status of the Super Research?" → account status; "add device
# <code>" → refused). Contract: every printed line is USER-SAFE (sr.py output
# is relayed verbatim). Non-destructive intents run immediately; destructive
# ones print the confirm question and the AI runs the real command on "yes".

# Both alternatives REQUIRE a digit — every real access code has one, and
# without it ordinary hyphenated words ("real-time", "high-tech") match the
# dashed form and hijack the message into device-add.
_NL_CODE_RE = re.compile(
    r"\b((?=[A-Z0-9-]*\d)[A-Z0-9]{4}-[A-Z0-9]{4})\b|\b((?=[A-Z]*\d)[A-Z0-9]{8})\b", re.I)
# Double quotes only (straight + curly). Apostrophes are NOT delimiters — a
# contraction + possessive ("what's … Tesla's …") would otherwise extract the
# garbage between them as a run title.
_NL_QUOTED_RE = re.compile(r"[\"“]([^\"“”]+)[\"”]")
# ⛔ THE CATCH-ALL IS NAMED ONCE. The negation veto has to land on exactly these
# words, and a second copy of a user-facing sentence two thousand lines away is
# how this file'''s guards have drifted before.
_NL_CATCH_ALL = ("I didn’t catch a Super Research request in that. I can research "
                 "a topic, check a run’s status, fetch its podcast or links, list "
                 "your researches, manage your devices, find a public computer and "
                 "ask to use it, and — for a computer you own — answer the people "
                 "asking for it and set whether strangers can find it at all — "
                 "what would you like?")
# The research-verb pattern, anchored at message start. Checked EARLY (before
# the control/status rules) so a research request whose TOPIC contains words
# like stop/pause/status/podcast ("research how to stop smoking") can never be
# hijacked into a run-control or status command.
# ⛔⛔ ONE LEAD-IN LIST. A conversational opener is not part of any request, and
# an anchored test that does not allow for one is broken by the word "so" —
# measured: `so are all my computers public?`, `and are …`, `hey are …` all
# stopped being read as QUESTIONS and reached the publish confirm, which then
# offered to publish "that computer" with no name, so a "yes" published whichever
# one the picker landed on. The research pattern below already allowed for these
# words and the state-question test did not.
_NL_LEAD_IN = r"(?:please |can you |could you |would you |hey |ok |okay |go |now |so |and |also |then |just )*"
_NL_RESEARCH_RE = re.compile(
    r"^" + _NL_LEAD_IN
    + r"(?:(?:do|run|start|fire|kick ?off|launch|begin) (?:a |another |the )?)?"
    r"(?:super ?research|deep[- ]?research|deep[- ]?dive|research|look into|"
    r"investigate|dig into|analy[sz]e)\b(?: on| into| about| for| of)?\s*(.*)$",
    re.I)
# Words that mean "the current run", not a run name — drop, don't pass as title.
_NL_GENERIC_RUN = {"it", "that", "this", "them", "run", "the run", "this run",
                   "that run", "the current run", "current run", "the research",
                   "research", "the last one", "everything",
                   # the product's own name is never a run title
                   "super", "super research", "the super research"}
# ⛔⛔ DERIVED FROM THE COMMAND'S OWN MAPS, because hand-written they went short
# and the shortfall was invisible: `sr skip audio` and `sr skip youtube` work at
# the CLI and `skip the audio` reached the router's bare form, which resolves the
# run's current BLOCKER instead — a mutating act nobody asked for. Same for
# `openai` and `anthropic`, which `_SKIP_AGENTS` maps and this list did not.
# ⭐ Longest-first so "chatgpt" wins its own substring "gpt" when rendering back.
_NL_PHASE_WORDS = tuple(sorted(dict.fromkeys(_SKIP_NAMES), key=len, reverse=True))
_NL_AGENT_WORDS = tuple(sorted(dict.fromkeys(_SKIP_AGENTS), key=len, reverse=True))
# Every phase the CLI can be told to skip, as numbers — the complement set an
# "all but X" ask has to be turned into.
_SKIP_PHASE_NUMBERS = tuple(sorted(set(_SKIP_NAMES.values())))
_NL_SKIP_ONE_RUN = ("I skip one run at a time. Ask me to list the running "
                    "ones and name it — nothing changes until you do.")
# Destructive verbs → the user-facing confirm question (AI runs the real
# command on "yes"; mirrors the SKILL.md Safety confirm-first list).
# The quote marks a person or a chat runtime can wrap a name in. ⛔ ALL SIX:
# the picker prints curly doubles, phones substitute curly singles, and a
# hand-typed reply uses straight ones.
# ⛔⛝ ONE MACHINE-NOUN LIST FOR THE WHOLE FILE, AND IT IS MODULE LEVEL FOR A
# MEASURED REASON. 7.9-3 unified two copies inside `_nl_resolve` after they had
# drifted by two words and silently broke four guards — and then cross-verify
# found THREE MORE copies elsewhere in the same function, each missing `mac`,
# `macbook` and `workstation`. So "remove my mac" and "unlink my macbook"
# reached the catch-all while "remove my computer" worked, and the comment
# claiming the list was unified was false when it was written. Every site that
# asks "is a computer being talked about" now reads this one name.
_MACHINE_NOUNS = (r"computers?|devices?|machines?|nodes?|pcs?|laptops?"
                  r"|macs?|macbooks?|desktops?|workstations?")
# ⛔⛔ THE WORDS PEOPLE SAY, WHICH IS NOT THE SAME LIST. `phone` belongs here and
# NOT in `_MACHINE_NOUNS`: nothing in this product is a phone, so it can never be
# a machine NAME either, and `_MACHINE_NOUNS` is read by the leading-noun strip
# and the bare-noun test where that distinction matters. That decision is right
# and it stays — what was wrong is that FIVE separate sites then hand-spliced
# `|phones?` back on, and the sites that DIDN'T were the admission tests. So
# `hide my phone` reached the catch-all while `hide my phones` got the set
# refusal, and `remove my phone` worked. One constant, every reader.
def _alt(words: "tuple[str, ...]") -> str:
    """A safe alternation: longest first, and ALWAYS its own group.

    ⛔ A constant that leaks alternatives is the 7.9-5 defect's own shape — see
    the note above `_MACHINE_PLURAL`. Never return a bare `a|b`.
    """
    return "(?:" + "|".join(sorted(set(words), key=len, reverse=True)) + ")"


_MACHINE_NOUNS_SAID = _MACHINE_NOUNS + r"|phones?"
# The verbs that unlink a machine. `drop` is one of them and reached the
# catch-all; spelled at the gate and not at the capture, it then reached a
# confirm with no name at all.
_UNLINK_VERBS = r"(?:remove|unlink|forget|delete|drop)"


# ⛔⛔ FOUR OF THESE WORDS ARE ALSO WORDS PEOPLE PUT IN A MACHINE'S NAME, and
# widening the leading-noun strip to the whole list ate them: "switch to the Mac
# Studio" looked up “Studio”, "remove my MacBook Air" offered to unlink “Air”, and
# "switch to the Workstation 3" reached for “3”. Cross-verify caught all three.
# ⭐ NOBODY NAMES A MACHINE "device" OR "computer" — those are the words the strip
# was written for and they can go unconditionally. `pc`, `laptop`, `mac`,
# `macbook`, `desktop` and `workstation` can only be stripped when what FOLLOWS
# them looks like an identifier rather than the rest of a name.
# ⛔ AND THIS FIXES TWO OLDER ONES ON THE WAY: `pc` and `desktop` were in the strip
# BEFORE this wave, so "PC Lab" and "Desktop Two" have been losing their first word
# all along.
_UNAMBIGUOUS_NOUNS = r"computers?|devices?|machines?|nodes?"
# ⛔ `phones?` IS HERE BECAUSE THE UNLINK RULE ADMITS IT AS A THING PEOPLE SAY. It
# was in the bare-noun test and not in the strip, so "remove my phone LABPC001"
# quoted “phone LABPC001” back — the defect this strip exists to prevent.
_NAMEABLE_NOUNS = r"pcs?|laptops?|macs?|macbooks?|desktops?|workstations?|phones?"


def _looks_like_an_identifier(rest: str) -> bool:
    """True for "LABPC001" and "PC2"; false for "Studio", "Air" and "3".

    ⛔ IT NEEDS A LETTER AND EITHER DIGITS OR ALL-CAPS. "3" alone is the tail of
    "Workstation 3", which is a name; "Studio" and "Air" are ordinary words in
    title case. An identifier is the shape the strip exists for and nothing else.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", rest or ""):
        return False
    if not any(c.isalpha() for c in rest):
        return False
    return rest.isupper() or any(c.isdigit() for c in rest)


def _strip_leading_noun(name: str) -> str:
    """Drop a leading category word — but never the first word of a NAME.

    ⛔⛔ A REMAINDER THAT OPENS WITH A CONJUNCTION IS PROOF THE STRIP WAS WRONG.
    `switch to my Nodes and Bolts PC` came out of here as "and Bolts PC" — the
    name's own first word is a device noun, so it was read as a category word and
    dropped, welding a dangling `and` onto the front of a machine name. The A/B
    against the pre-build revision is what showed it, and it showed it only
    because the conjunction signal had just stopped refusing these names: the
    strip had always been wrong here, and the refusal was hiding it. ⛔ A fix that
    turns a WRONG REFUSAL into a WRONG ACTION is not a fix, so this guard ships in
    the same change as the signal that exposed it.
    ⛔⛔ AND A REMAINDER THAT NAMES NOTHING IS THE SAME PROOF. `my Nodes Mac` has a
    device noun for its FIRST word and a device noun for its LAST, so stripping the
    first leaves "Mac" — a bare noun, which every caller blanks. Wave 1.2 gave this
    strip to the visibility branch and instantly lost the name on twenty frames of
    that one machine. A strip that leaves nothing behind did not find a category
    word; it ate half a name. Same principle as `_trim_trailing_clause`'s own
    never-return-empty guard, and it was missing here.
    """
    def _kept(rest: str, whole: str) -> str:
        # ⛔⛤ AND IT LOOKS PAST A TAIL WORD. `my Nodes Mac today` left “Mac today”,
        # which is not a bare noun — so the guard passed and the strip still ate
        # half the name. What matters is whether the remainder names anything
        # once the words a name can END in are set aside.
        if _is_bare_machine_noun(rest) or _is_bare_machine_noun(
                re.sub(rf"[\s,;]+{_NAME_TAIL_COMMA_ONLY}$", "", rest, flags=re.I)):
            return whole
        # ⛔ THE WORD BOUNDARY IS WHY `&` SLIPPED THROUGH THIS GUARD. `\b` after a
        # `&` needs a word character on ONE side only, and `"& Bolts"` has a
        # space there — so `hide "Nodes & Bolts"` had its first word eaten as a
        # category noun and came out as “& Bolts”. The guard was right; its
        # anchor was wrong. Symbols get no boundary; words keep theirs.
        return whole if re.match(r"^(?:(?:and|or|plus|as\s+well\s+as)\b|[&+])",
                                 rest, re.I) else rest
    whole = (name or "").strip()
    m = re.match(rf"^(?:{_UNAMBIGUOUS_NOUNS})\s+(.+)$", whole, re.I)
    if m:
        return _kept(m.group(1).strip(), whole)
    m = re.match(rf"^(?:{_NAMEABLE_NOUNS})\s+(.+)$", whole, re.I)
    if m and _looks_like_an_identifier(m.group(1).strip()):
        return _kept(m.group(1).strip(), whole)
    return whole


# ⛔⛔ ONE PREDICATE FOR "IS THIS A SET", AND IT REPLACES `_is_bulk_machine_phrase`
# RATHER THAN SITTING BESIDE IT. 7.9-5 added a second answer to the same question
# and the two disagreed; worse, the duplication produced an EQUIVALENT MUTANT twice
# in the Gemini wave, which is a harness bug and not a survivor. The fold was
# measured before it was made: 17 of the 18 captured-name shapes the 7.9-4 gate
# answers are identical, and the single disagreement is "All Dev Laptops" — a
# genuinely plural machine NAME, the residue this design rules acceptable with
# quoting as the escape.
#
# ⛔⛔ AND THE SIGNAL IS A PLURAL NOUN, NOT A QUANTIFIER. Every defect in 7.9-5
# came from classifying a string by its quantifier behind a wildcard filler
# `(?:\w+\s+)?`, which full-matched any real machine name shaped
# "<all|every|each|both> <word> <machine-noun>" — 96 measured phrases, 12 names
# across 8 verbs, so "All Hands Mac" could not be unlinked, published, hidden,
# asked for, approved or denied while "switch to All Hands Mac" still resolved it.
# THERE IS NO WILDCARD IN THIS FILE'S ANSWER. A quantifier counts only when it
# binds the noun through a DETERMINER slot, and "Hands" is not a determiner.
#
# ⭐ MEASURED BEFORE IT WAS BUILT, over 384 generated two- and three-token names
# across 8 verbs plus the 186 phrases SKILL.md and the routing tests already feed
# this resolver: 0 names caught, 43 of 44 bulk phrases caught. Every one of the 12
# corpus hits is a `show my computers`-shaped LIST request, which is why this
# predicate is consulted ONLY inside the branches that ACT on one target — see
# each call site. A set on a reading verb is a list to serve, never a refusal.
# ⛔⛔ EVERY ONE OF THESE CARRIES ITS OWN GROUP, AND THAT IS NOT A STYLE CHOICE.
# I wrote `_QUANTIFIERS` as a bare `all|every|each|both|any` first, interpolated it
# into a larger alternation, and `all` became a TOP-LEVEL alternative of that
# alternation — so the bare word "All" in "All Hands Mac" matched, and all 384
# generated names classified as sets. That is the 7.9-5 defect's own shape,
# reintroduced by me in the predicate written to replace it, and caught only
# because the name corpus ran against the live code and not against my model of
# it. A constant that is safe to interpolate ANYWHERE cannot leak alternatives.
_MACHINE_PLURAL = "(?:" + _MACHINE_NOUNS_SAID.replace("s?", "s") + ")"
_MACHINE_SINGULAR = "(?:" + _MACHINE_NOUNS_SAID.replace("s?", "") + ")"
# ⛔ RUN NOUNS ARE A SEPARATE LIST BECAUSE `research` IS A MASS NOUN. "stop all of
# my research" names a set with no plural form anywhere in it, so a plural-only
# test cannot see it — measured, it was one of this design's 17 original misses.
_RUN_PLURAL = r"(?:runs|researches|reports|briefs)"
_RUN_MASS = r"(?:research|work)"
_QUANTIFIERS = r"(?:all|every|each|both|any)"
# ⛔⛔ `any` IS NOT A TOTALISER AND THE OWNER MEASURED THAT. `stop any run` and
# `approve any` mean "whichever one" and were on 7.9-5's TOO-WIDE list — refusing
# them is a defect. `every run` and `each run` mean all of them. So the singular
# noun `run` binds only to the totalising quantifiers, while `any of my
# computers` keeps working through the PLURAL reading, where `any` belongs.
_QUANTIFIERS_TOTAL = r"(?:all|every|each|both)"
# The determiner slot. ⛔ NO WILDCARD MAY EVER JOIN IT — that is the 7.9-5 defect.
# ⛔⛔ COMPOSED, NOT ENUMERATED. I wrote it as a flat list of whole phrases first
# and it went short on the first combination nobody had listed — `all the public
# computers` matched neither `the\s+` nor `public\s+` because it needs BOTH. A
# list of combinations is a list that is always one combination behind; three
# independent optional slots cover them all and cannot go short.
# ⛔ AND EVERY SLOT IS STILL A CLOSED LIST. No wildcard may join any of them —
# that is the 7.9-5 defect, and a `\w+` here would re-open all 96 phrases.
_SET_OF = r"(?:of\s+|one\s+of\s+)?"
_SET_POSS_WORD = r"(?:my|the|your|their|our|his|her|its)\s+"
_SET_COUNT = r"(?:\d+|two|three|four|five|six|seven|eight|nine|ten)\s+"
_SET_ADJECTIVE = r"(?:public|private|hidden|other|remaining|spare|old|new)\s+"
_SET_DETERMINER = (rf"(?:{_SET_OF}(?:{_SET_POSS_WORD})?(?:{_SET_COUNT})?"
                   rf"(?:{_SET_ADJECTIVE})?)")


# ⛔⛔ THE THREE SIGNALS ARE NAMED AND COMPILED SO A TEST CAN REACH THEM. The
# 7.9-5 gate's patterns were built inline, which is why nothing could assert that
# it carried no wildcard filler. Each is also proved LOAD-BEARING in the tests:
# for each one there is a phrase that only it catches.
# 1. A PLURAL machine or run noun — the signed signal — but it must be a POSSESSED
#    HEAD, not a bare word anywhere in the message.
# ⛔⛔ I SHIPPED IT AS A BARE WORD AND CROSS-VERIFY MEASURED FIFTEEN FALSE
# POSITIVES, every one a regression against the revision this wave started from.
# `unlink my Nodes Mac`, `hide my Backup PCs Room` and `remove my Reports Desktop`
# are SINGULAR machines whose NAMES contain a plural word; `stop the laptops
# comparison` and `stop my research how to compare laptops` are research TOPICS —
# and this is a research product, so a topic containing `reports` or `laptops` is
# ordinary. The design authorised one residue, "a genuinely plural machine NAME";
# a bare-word match is far wider than that and was never authorised.
# ⭐ TWO REQUIREMENTS, BOTH MEASURED OVER THE WHOLE CORPUS. The plural must be
#   · POSSESSED — `my`/`our`/`the`/… immediately before it, optionally with a
#     count. "Francois Laptops" has no determiner and is cleared by this alone.
#   · THE HEAD of its phrase — nothing after it but the end, punctuation, or a
#     word that cannot continue a name. "my Nodes Mac" has "Mac" after the
#     plural, so the plural is not what is being asked about.
_SET_POSSESSIVE = rf"{_SET_POSS_WORD}(?:{_SET_COUNT})?(?:{_SET_ADJECTIVE})?"
# ⛔ THE CONTINUATIONS ARE A CLOSED LIST, and they are the words a VERB needs
# after its object — not words a name can contain.
# ⛔⛔ `and`/`or` CAME OUT OF THIS LIST ON 09-11, AND THEY WERE MY OWN REGRESSION.
# I added them so `hide all my computers and my laptops` would still read as a
# set, and in doing so I reopened the exact hole the head test exists to close:
# `hide my Nodes and Bolts PC` is ONE machine whose name's first word happens to
# be a plural device noun, and it came back "I hide one computer at a time".
# 84 phrasings measured. The head test was written to stop `my Nodes Mac`; a
# continuation of `and` lets any name whose SECOND word is a device noun satisfy
# it. The sets those two words were carrying are carried properly now, by the
# conjunction signal below — which is the reading they always needed.
# ⛔⛔ THE WORDS THAT END A NAME, IN TWO HALVES, AND EVERY CONSUMER DERIVES FROM
# THEM. The set head used to spell this list inline, and wave 1.2 measured the
# cost of that: a POLITENESS word ran into the captured name at six separate
# capture sites — `hide my Studio PC please` refused “Studio PC please” — while
# the only list in the file that already knew those words end a name sat right
# here, unread by any of them. 592 of 7,091 driven phrasings broke on a word the
# person added to be polite.
# ⛔ THE HALVES ARE NOT INTERCHANGEABLE. The polarity half belongs to the COMMAND
# — trimming `public` off a name would delete the instruction — so only the
# adverbial half is a name tail. Splitting them here is what lets one list serve
# both readers without a fifth hand copy going short. (7.9-5b, 1.1.)
_NAME_END_POLARITY = ("public", "private", "hidden", "unlisted", "findable",
                      "discoverable", "visible")
_NAME_END_ADVERB = ("alone", "too", "please", "now", "also", "instead",
                    "again", "anymore", "today")
_SET_HEAD = (r"(?=\s*$|[,.;:!?]|\s+(?:"
             + "|".join(_NAME_END_POLARITY + _NAME_END_ADVERB) + r"))")

# The politeness a person adds that no machine, run or person is named after.
# ⛔ SEPARATE FROM THE ADVERBS ON PURPOSE: these are multi-word and none of them
# is in the set head, so they cannot be derived from it — but they also carry no
# risk, because nothing is called “thank you”.
_POLITE_TAIL = (r"(?:pls|plz|thanks|thank\s+you|thx|ta|cheers|for\s+me|"
                r"if\s+you\s+(?:can|could|would)|"
                r"when(?:ever)?\s+you\s+(?:can|get\s+a\s+chance|have\s+time)|"
                r"right\s+(?:now|away)|ok|okay|asap|for\s+now|of\s+course)")
# ⛔⛔⛔ THE TAIL LIST SPLITS BY CONSEQUENCE, AND CROSS-VERIFY IS WHY. Trimming
# every word in `_NAME_END_ADVERB` unconditionally produced the one outcome this
# file refuses above all others: an act on the WRONG MACHINE. Measured, on an
# account holding both “Studio PC Now” and “Studio PC” —
#     `hide my Studio PC Now`      HID “Studio PC”, no confirm
#     `switch to my Studio PC Now` SWITCHED to “Studio PC”, no confirm
#     `remove my Studio PC Now`    offered to UNLINK the wrong one
#     `ask for Studio PC Now`      disclosed the asker to the wrong OWNER
# 118 distinct name→machine pairs, 430 of them on branches that do not confirm.
# The truncation is always a SUBSTRING of the real name, so the real machine
# always matches too — the wrong one wins whenever the account holds a machine
# whose whole name equals the truncation, which is exactly what a person does
# when they buy a second one.
# ⭐⭐ SO THE WORDS SPLIT. Nobody calls a machine “please” or “thanks”, and those
# fixed 592 phrasings at no risk. `now`, `today`, `also`, `alone`, `too`, `again`,
# `anymore`, `instead` all appear in real names, so they come off only behind a
# COMMA — `hide my mac, now` yes, `hide my Studio PC Now` no.
# ⛔ A FIX THAT TURNS A WRONG REFUSAL INTO A WRONG ACTION IS NOT A FIX. This
# file's own words, from the wave before this one.
# `please` sits with the polite words, not the adverbs: it is the single
# commonest one and no machine is called it.
# ⛔ BUILT BY INTERPOLATION, NOT BY PULLING WORDS OUT OF A REGEX. My first version
# ran `findall` over `_POLITE_TAIL`'s SOURCE and harvested a bare `now` out of
# `right now` — so `hide my Studio PC Now` lost its last word again, by a road the
# split was written to close. A pattern is not a word list.
_NAME_TAIL_ALWAYS = rf"(?:please|{_POLITE_TAIL[3:-1]})"
_NAME_TAIL_COMMA_ONLY = _alt(tuple(w for w in _NAME_END_ADVERB if w != "please"))
# ⛔ TWO PATTERNS, NOT ONE ALTERNATION, because the caller treats them
# differently: a COMMA is the person separating the tail from the name, so a
# bare-noun remainder after one is the picker and correct; a SPACE leaves no
# such evidence, so a bare-noun remainder there means the trim ate half a name.
_NAME_TAIL_SPACED = re.compile(rf"(?:\s*[,;]\s*|\s+){_NAME_TAIL_ALWAYS}"
                               rf"\s*[.!?]*$", re.I)
_NAME_TAIL_COMMAED = re.compile(rf"\s*[,;]\s*(?:{_NAME_TAIL_COMMA_ONLY[3:-1]}|"
                                rf"{_NAME_TAIL_ALWAYS[3:-1]})\s*[.!?]*$", re.I)
_SET_SIGNAL_PLURAL = re.compile(
    rf"\b{_SET_POSSESSIVE}(?:{_MACHINE_PLURAL}|{_RUN_PLURAL})\b{_SET_HEAD}", re.I)
# 2. A QUANTIFIER BINDING A SINGULAR noun through the determiner slot. `hide every
#    computer` and `every computer i have` use the singular form, so signal 1 is
#    blind to them. ⛔ IT BINDS THROUGH A DETERMINER, NEVER A WILDCARD — "Hands"
#    is not a determiner, which is the whole reason "All Hands Mac" survives.
# ⛔ THE PLURAL NOUNS BELONG HERE TOO, now that signal 1 requires a possessive.
# `stop all my runs` and `stop all three runs` have a quantifier and no possessive
# before the noun, so signal 1 cannot see them and this is the only reading left.
# ⛔ AND THE SINGULAR NOUN THIS FILE USES FOR A RUN WAS MISSING ENTIRELY. `_RUN_MASS`
# is research|work and `_RUN_PLURAL` is plural-only, so nothing saw `every run`,
# `each run` or `every run i have` — and pause/resume/retry EXECUTE with no
# confirm, so those three ran against whichever run was current. Cross-verify
# measured it on all three.
_SET_SIGNAL_QUANTIFIED = re.compile(
    rf"\b(?:{_QUANTIFIERS}\s+{_SET_DETERMINER}"
    rf"(?:{_MACHINE_SINGULAR}|{_MACHINE_PLURAL}|{_RUN_MASS}|{_RUN_PLURAL})"
    rf"|{_QUANTIFIERS_TOTAL}\s+{_SET_DETERMINER}runs?)\b", re.I)
# 3. A COLLECTIVE OF PEOPLE. ⛔⛔ THE CONSENT SURFACE HAS NO MACHINE NOUN AT ALL —
#    the set there is of PEOPLE — so the signed signal missed the whole queue.
#    It matters most: those phrases capture NOTHING, `_resolve_asker("")` returns
#    the sole waiting row, and one stranger is let onto the machine (or one person
#    refused for seven days) while the person believes they answered the queue.
# ⛔⛔ `but|except|apart` JOINED THE CONTINUATIONS IN *BOTH* COPIES. `approve
# everyone but Sam` stopped being a set the moment I narrowed bare `but` out of
# the exclusion vocabulary: nothing blanked "but Sam", so `everyone` was no longer
# at the head of its phrase. ⛔ The file already records adding a guard to the
# collective signal and then writing the totaliser without it — the same miss
# twice in one file — so this edit asserts it changed TWO sites, not one.
_SET_SIGNAL_COLLECTIVE = re.compile(
    # ⛔ `everyone`/`everybody` NEEDS THE HEAD TEST TOO — a person can be labelled
    # "Everyone Smith", and cross-verify found `approve Everyone Smith` refused.
    rf"\b(?:them all|all of them|"
    rf"(?:everyone|everybody)(?=\s*$|[,.;:!?]|\s+(?:waiting|pending|who|in\b|else|but|except|apart|other\s+than))|"
    rf"{_QUANTIFIERS}\s+(?:the\s+)?(?:pending|waiting|queued)|"
    rf"the queue|the rest|{_QUANTIFIERS}\s+{_SET_DETERMINER}"
    rf"(?:requests?|asks?|people|askers?|pending))\b", re.I)
# 4. A TOTALISING GENERIC — the words that mean "all of the things".
# ⛔⛔ THE ROOT CAUSE CROSS-VERIFY NAMED, AND IT UNIFIES FOUR SURFACES: the words
# the collective signal was blind to are EXACTLY the words this file's three
# capture-blankers erase to "" — `_NL_GENERIC_RUN` for the run verbs, the `_who`
# fullmatch for consent, the `_vis_obj` fullmatch for hide. So a blank capture IS
# the tell that a collective was said, and the message no longer holds anything
# the other signals recognise. Measured: `pause everything`, `resume them` and
# `retry all of it` EXECUTED with no confirm; `stop everything` and `approve the
# whole queue` reached confident single-target confirms.
# ⛔ BARE `all`, `both`, `any`, `one` AND `ones` ARE DELIBERATELY ABSENT. 7.9-5's
# TOO-WIDE list has `approve Any`, `deny Both` and `approve any` on it: a lone
# quantifier is as likely to be a name or an abbreviation as a set, and
# `_resolve_asker` already asks which one when more than one is waiting. What is
# gated here is a totalising PHRASE, plus the three words that can only ever mean
# everything.
# ⛔⛔ BARE `them` IS OUT, AND THE PRODUCT'S OWN CORPUS IS WHAT REMOVED IT.
# English has a singular `them`: `let them use my computer` is one of the
# phrasings this client teaches, and it means ONE person. The A/B over SKILL.md
# and the routing tests caught it on the first run — which is the argument for
# replaying the product's own phrases as a test rather than as a one-off.
# ⭐ `them all` and `all of them` stay: those cannot be singular.
# ⛔ AND `everyone`/`everybody` CARRY THE HEAD TEST HERE TOO. I added it to the
# collective signal, then wrote this one without it — the same miss twice in one
# file — so `approve Everyone Smith` came back refused again.
# ⛔⛔ `everything` CARRIES A PREPOSITION TEST, AND THAT TOO WAS MY REGRESSION.
# `run everything on my Studio PC` came back "I run on one computer at a time"
# while the branch's own capture spells `run (?:it |everything )?on` verbatim —
# my gate refused the product's own documented phrasing. `everything` followed by
# a preposition is the OBJECT OF THE RUN, not a set of machines: one computer is
# named right after it. `pause everything` and `stop everything` still fire.
# ⛔⛔⛔ `everything` IS A TOTALISER ON EVERY SURFACE, AND THE ONE EXEMPTION LIVES
# ON THE SWITCH BRANCH, NOT HERE. I put it here first and cross-verify measured
# FIVE regressions from it: `pause everything on my mac` EXECUTED a pause on
# "mac", `retry everything on my mac` EXECUTED, `stop everything on my mac`
# confirmed Stop "mac", `pause everything to do with tesla` EXECUTED, and
# `hide everything in my devices list` EXECUTED an unconfirmed hide. Narrowing the
# lookahead to `everything on <determiner> <machine>` did not help, because that
# is exactly the shape `pause everything on my mac` has too.
# ⭐ THE WORD MEANS DIFFERENT THINGS ON DIFFERENT SURFACES — "all the runs" to a
# run verb, "the whole research" to the switch verb — so a signal shared by both
# surfaces cannot carry the exemption. It belongs where the product's own wording
# is, and that is the switch branch alone.
_SET_SIGNAL_TOTALISER = re.compile(
    r"\b(?:everything|"
    r"(?:everyone|everybody)(?=\s*$|[,.;:!?]|\s+(?:waiting|pending|who|in\b|else|but|except|apart|other\s+than))|"
    r"them all|all of them|all of it|it all|both of them|"
    r"the (?:whole )?(?:lot|batch|queue|rest)|the pending ones|"
    r"anyone waiting|whoever(?:'s| is) waiting)\b", re.I)
# 5. A CONJUNCTION JOINING TWO NOUN PHRASES. ⛔⛔ THE SIGNAL 7.9-5b DID NOT HAVE,
#    AND THE ONE THAT LET A SET THROUGH ON EIGHT VERBS. With no shape for it,
#    `my mac and pc` reads as ONE machine with a funny name: `hide my mac and pc`
#    and `pause the tesla run and the ford run` EXECUTED with no confirm, and
#    `remove my mac and pc`, `approve my mac and pc`, `make my mac and pc public`,
#    `stop my tesla and ford runs`, `ask to use LABPC001 and LABPC002` and
#    `skip both my runs` each reached a CONFIDENT SINGLE-TARGET confirm — the
#    destructive unlink and the access grant among them.
# ⛔⛔⛔ AND THE DISCRIMINATOR IS NOT THE WORD `and`. That is the whole difficulty,
#    and it is measured, not argued: `hide my Rock and Roll PC`,
#    `unlink my Black and Decker Laptop`, `hide my Salt and Pepper Mac`,
#    `research tesla and ford` and `research the pros and cons of solar` are ONE
#    machine and two topics, and all five must keep working. A signal keyed on the
#    conjunction alone eats every one of them — which is the same mistake as the
#    bare plural, one wave later.
# ⭐⭐ SO IT IS KEYED ON A NOUN PHRASE ON BOTH SIDES, IN TWO SHAPES, AND NEITHER
#    HAS A FREE WILDCARD ON THE LEFT:
#      i. a noun, the conjunction, then a NEW DETERMINER and a noun at the head —
#         a repeated determiner starts a second phrase: `the Studio PC and THE Lab
#         Mac`, `the tesla run and THE ford run`, `my mac and MY pc`.
#     ii. a noun, the conjunction, then a BARE noun at the head — two bare nouns
#         cannot be one name: `my mac and pc`, `mac or pc`, `my mac & pc`.
#    `my Nodes and Bolts PC` satisfies NEITHER: after the conjunction comes
#    `Bolts`, which is not a determiner and not a noun. That single fact is what
#    separates the 84 false positives from the real sets, and it is why the two
#    shapes are written out rather than merged into one wildcard.
# ⛔ THE HEAD TEST STILL APPLIES TO THE SECOND NOUN, so `hide my Mac and PC Room`
#    stays a NAME — `Room` cannot continue a verb's object. And a machine really
#    called `Mac and PC` keeps the escape every residue in this file has: quote it.
_SET_CONJ = r"(?:\s*,\s*|\s*;\s*|\s+and\s+|\s+or\s+|\s*&\s*|"\
            r"\s+as\s+well\s+as\s+|\s+plus\s+|\s*,\s*and\s+|\s*,\s*or\s+|"\
            r"\s+but\s+also\s+|\s+along\s+with\s+|\s+together\s+with\s+)"
_SET_NOUN = (rf"(?:{_MACHINE_SINGULAR}|{_MACHINE_PLURAL}|{_RUN_PLURAL}|"
             rf"runs?|researches?|reports?|briefs?)")
# ⛔ SHAPE iii NEEDS A CONJUNCTION WITH NO LEADING SPACE. Its own token gap
# consumes the space before the conjunction, so `_SET_CONJ` — which requires one —
# could never match and `stop my tesla and ford runs` stayed a false confirm even
# after the shape was added. Measured, not reasoned: the shape was in the file and
# doing nothing.
_SET_CONJ_BARE = (r"(?:,\s*|;\s*|and\s+|or\s+|&\s*|as\s+well\s+as\s+|plus\s+|"
                  r"but\s+also\s+|along\s+with\s+|together\s+with\s+)")
# ⛔ THE GAP IN SHAPE i IS BOUNDED TO TWO TOKENS AND SITS BETWEEN A REQUIRED
# DETERMINER AND A REQUIRED NOUN-AT-THE-HEAD. An unbounded filler is how 7.9-5's
# wildcard ate real names; this one cannot start a match on its own, because a
# machine or run NOUN is required before the conjunction as well.
_SET_CONJ_NAMED = rf"{_SET_POSS_WORD}(?:{_SET_COUNT})?(?:{_SET_ADJECTIVE})?(?:[\w'-]+\s+){{0,2}}"
# ⭐ SHAPE iii — TWO NAMES SHARING ONE PLURAL HEAD. `stop my tesla and ford runs`
# means my tesla runs AND my ford runs: there is only ONE noun, at the end, and
# both shapes above need a noun on each side of the conjunction, so neither saw
# it. The possessive is not adjacent to the plural either, so the plural signal
# was blind too — it requires `my runs`, not `my tesla and ford runs`.
# ⛔ THE HEAD MUST BE PLURAL, and that single fact is what keeps it off
# `my Nodes and Bolts PC` — a singular head is a name, a plural head is a set.
# ⭐ A genuinely PLURAL machine name ("Rock and Roll PCs") is refused by this, and
# that is the residue this design already rules acceptable, with quoting as the
# escape — the same call the file makes for "All Dev Laptops".
_SET_SIGNAL_CONJUNCTION = re.compile(
    rf"\b{_SET_NOUN}\b{_SET_CONJ}"
    rf"(?:{_SET_CONJ_NAMED}{_SET_NOUN}|{_SET_NOUN})\b{_SET_HEAD}"
    rf"|\b{_SET_POSS_WORD}(?:[\w'-]+\s+){{0,2}}{_SET_CONJ_BARE}(?:[\w'-]+\s+){{0,2}}"
    rf"(?:{_MACHINE_PLURAL}|{_RUN_PLURAL})\b{_SET_HEAD}", re.I)
_SET_SIGNALS = (_SET_SIGNAL_PLURAL, _SET_SIGNAL_QUANTIFIED, _SET_SIGNAL_COLLECTIVE,
                _SET_SIGNAL_TOTALISER, _SET_SIGNAL_CONJUNCTION)
# ⛔ THE VISIBILITY SETTERS, ONE LIST. `_named_target` and the set arm below both
# need to know "did somebody ask to CHANGE something here", and two copies of a
# verb list two lines apart is exactly how `_machine_kw` and `_mine_kw` drifted by
# two words and silently broke four guards.
# ⛔⛔⛔ ONE LIST PER ROLE, AND EVERY READER DERIVES FROM IT. Wave 1.2 measured the
# price of the alternative: FOUR hand copies of the setter list existed (this one,
# `_polite_imperative`, the quoted arm of `_named_target`, and the explicit half of
# `_ACT_VERBS`, which re-listed eight words the splice already carried), plus TWO
# polarity lists neither derived from the other. **Every "dead word" defect in the
# wave was a copy that had gone short.** This is 7.9-5b's lesson and 1.1's lesson
# landing in the same place: a hand-written list goes short, and it goes short
# silently, because a missing word looks exactly like a word nobody says.
#
# ⛔⛔ AND THE SETTER LIST IS A TARGET LIST, NOT A SIGNAL LIST — measured, and it
# is the single fact that explains most of group B. The branch is admitted by
# `_public_kw | _offering_kw | _hiding_kw` alone, so a verb that lives only here
# cannot start anything. Proof in both directions: `my Studio PC public`, with no
# verb at all, reached the publish confirm, while `publish my Studio PC` reached
# the DEVICE LIST. Eleven of the sixteen words were in no signal.
#
# THE ROLES, and what each one means:
#   POLAR   — needs a polarity word after the name:  "make X public"
#   HIDE    — is itself the hide, no polarity word:  "unlist X"
#   PUBLISH — is itself the publish, no polarity word: "offer X"
#   OFF     — "take X off the list" — needs the off/out-of/from shape
_VIS_POLAR_VERBS = ("make", "set", "switch", "turn", "put", "take")
_VIS_HIDE_VERBS = ("hide", "unlist", "unpublish", "delist", "disable",
                   "unshare", "deregister")
# ⛔ `list` AND `post` ARE DELIBERATELY ABSENT. `list` is the device-LIST request
# word — admitting it here would hand every "list my computers" to the visibility
# branch — and `post` collides with posting a brief. `register` is absent because
# "register my computer" is how people ask to PAIR one.
_VIS_PUBLISH_VERBS = ("publish", "offer", "share", "advertise", "expose")
_VIS_OFF_VERBS = ("take", "remove", "drop", "pull")


def _inflect(verbs: "tuple[str, ...]") -> "tuple[str, ...]":
    """bare, -s and -ing for each verb — BUILT, never typed.

    ⛔⛔ WAVE 1.2 MEASURED THAT NO `-s` FORM ANYWHERE IN THIS FILE FIRED, and that
    the two sides were exact inverses: the hide side had only the BARE form
    (`hiding my mac` was dead) and the publish side only the `-ing` form
    (`offer my mac` was dead, `offering my mac` worked). Nobody chose that; it is
    what two hand-written lists drift into.
    """
    out = []
    for v in verbs:
        out.append(v)
        out.append(v + "es" if re.search(r"(?:sh|ch|s|x|z)$", v) else v + "s")
        out.append(v[:-1] + "ing" if v.endswith("e") else v + "ing")
    return tuple(sorted(dict.fromkeys(out), key=len, reverse=True))



_VIS_SETTERS = _alt(_VIS_POLAR_VERBS + _VIS_HIDE_VERBS + _VIS_PUBLISH_VERBS
                    + _VIS_OFF_VERBS)
_VIS_HIDE_ALL = _alt(_inflect(_VIS_HIDE_VERBS))
# The polarity words that MEAN hidden — one list, read by the hide signal and by
# the negation test that inverts it. They were two lists that had drifted apart.
# ⛔⛔ THE POLARITY WORDS SPLIT BY SIDE, BECAUSE THE SIDES ARE NOT
# INTERCHANGEABLE — 1.1's asymmetry, and deriving the publish-side negation test
# from the WHOLE list broke it within minutes: negating a PUBLISH is a concrete
# hide, so `make my mac not private` is a publish; negating a HIDE names no state
# at all, so it is not a command. Two of 1.1's own tests caught it. One list per
# side, and a union for the readers that want both.
_PUBLISH_POLARITY_WORDS = ("public", "publicly", "findable", "discoverable",
                           "visible", "shared", "sharing", "listed")
_HIDE_POLARITY_WORDS = ("private", "hidden", "unlisted", "invisible",
                        "undiscoverable")
_HIDE_POLARITY = _alt(_HIDE_POLARITY_WORDS)
# Every word that can sit after a name and mean "this is the setting". The name
# ends where one of these begins — which is exactly what `_SET_HEAD` uses its
# polarity half for, so the two are the same list plus the two hide-only words
# that were never in it. `make my Studio PC undiscoverable` dropped the name for
# want of them.
# ⛔ THE `-ly` FORMS ARE HERE AND NOT IN `_NAME_END_POLARITY`, which also builds
# the set head. `\bpublic\b` does not match "publicly", so `list my Studio PC
# publicly` and `offer my Studio PC publicly` reached the confirm with NO NAME —
# a word the polarity list has held all along, in a spelling it never had.
_VIS_POLARITY_ALL = _alt(_NAME_END_POLARITY + ("invisible", "undiscoverable",
                                               "publicly", "privately"))
# The determiners a name can hide behind. Spelled separately at four capture
# sites, they disagreed: unlink stripped eight, switch stripped two, and the six
# switch was missing rode into a lookup that cannot resolve them.
_NAME_DETERMINER = _alt(("the", "a", "an", "my", "our", "your", "their", "its",
                         "his", "her", "that", "this"))
_VIS_PUBLISH_ALL = _alt(_inflect(_VIS_PUBLISH_VERBS))

# ⛔⛔⛔ A NEGATION IS NOT THE VERB IT CONTAINS — AND THIS FILE ALREADY KNEW THAT.
# The decide clause carries `_negated_decide` with the whole vocabulary and the
# right landing written beside it: "what the person wants is a hide or a sharer
# removal, and guessing between them is worse than the catch-all." ONE branch
# consulted it. Nothing else did, and the measurement is brutal: **81 of 112
# negated forms still reached the action**, across eight surfaces.
#   `don'''t send the logs`            SENT THE LOGS to support
#   `don'''t hide my studio pc`        HID IT          `no need to hide my mac` HID IT
#   `don'''t pause the run`            PAUSED IT       `don'''t resume the Mars run` RESUMED IT
#   `don'''t add device K7XQ-9B2M`     PAIRED IT       `please don'''t switch to the office PC` SWITCHED
# ⛔⛔ AND IT DID NOT ONLY FAIL TO VETO — IT REROUTED. `don'''t research the pause
# feature` came back ['pause','feature']: the research branch bailed on the
# negation (correctly), and a LATER branch then picked the verb out of the topic.
# ⛔ `don'''t` AND `do not` ALSO ANSWERED THE SAME SENTENCE DIFFERENTLY —
# `don'''t hide my studio pc` hid it, `do not hide my studio pc` listed devices.
# ⭐⭐ TWO SHAPES, AND ONLY TWO — MEASURED, NOT ARGUED:
#   · a negator IMMEDIATELY BEFORE THE VERB vetoes the whole command. The landing
#     is the catch-all, on this file'''s own precedent.
#   · a negator IMMEDIATELY BEFORE THE POLARITY WORD inverts that word:
#     `make my mac not private` is a PUBLISH, and it executed a hide.
#   · a negator ANYWHERE ELSE belongs to a NAME and is ignored — which is the
#     whole reason the window is adjacency and not a 40-character span:
#     `make my Now or Never Mac public` HID a machine whose own name says "Never".
# ⛔⛔⛔ THE APOSTROPHE A MAC ACTUALLY TYPES IS THE CURLY ONE, and this vocabulary
# only ever spelled the straight `'`. Smart quotes are ON BY DEFAULT on macOS and
# iOS, and SKILL.md relays the user's sentence VERBATIM — so `don’t` arrived here
# and EVERY veto in this file was off. Measured on the shipped router, same
# sentence, two apostrophes: `don’t send the logs` SENT THEM; `don’t hide my
# studio pc` HID IT, unconfirmed; `don’t make my mac public` offered to PUBLISH
# it; `don’t add device K7XQ-9B2M` PAIRED IT; `please don’t switch to the office
# PC` SWITCHED; `don’t pause the run` PAUSED IT. 12 of 13 negatable bases failed
# for `don’t `. The file already spells both apostrophes at four other sites
# (`(?:’s|'s)`, `(?!['’-])`); these contraction copies were the ones that did not.
# ⛔⛔ AND THE FIX IS A CHARACTER CLASS, NEVER A NORMALISE-TO-ASCII AT THE TOP OF
# `_nl_resolve`. `t` there feeds EVERY NAME CAPTURE, so rewriting `’` to `'`
# would make `hide Sam’s Mac` capture the name "Sam's Mac" and miss the exact-name
# lookup against the real device document — trading a missed veto for acting on
# the wrong machine. The class touches the vocabulary only, and nothing else.
_NEG_WORDS = (r"(?:don['’]?t|dont|do\s+not|does\s+not|doesn['’]?t|never|"
              r"no\s+longer|not|cannot|can['’]?t|shouldn['’]?t|should\s+not|"
              r"won['’]?t|will\s+not|would\s+not|"
              r"no\s+need\s+to|don['’]?t\s+want\s+to|stop\s+trying\s+to|quit|"
              r"rather\s+not|please\s+don['’]?t)")
# ⛔ THE INTERVENING WORDS ARE A CLOSED LIST. A free span here is how the old
# 40-character negation arm came to read a machine NAME as a negation.
# ⛔⛤ `keep` JOINED AFTER CROSS-VERIFY. `don't keep hiding my Studio PC` ran an
# UNCONFIRMED HIDE — the ask was to STOP hiding it. The gerunds entered the act
# verbs this wave, and the filler between the negator and the verb had never had
# to carry `keep` before, because no `-ing` form could be the verb.
_NEG_FILLER = r"(?:\s+(?:you|i|we|it|to|please|ever|even|really|actually|just|bother(?:ing)?|keep|keeps|continue|carry\s+on|want\s+to|need\s+to|try(?:ing)?\s+to))*"
# ⭐ THE ACT VERBS, DERIVED FROM THE INVENTORIES THAT ALREADY EXIST rather than
# hand-written a fourth time — a hand-written copy is what left `status` out of
# the pairing guard and every visibility verb out of its sibling.
# ⛔ THE SPLICE ALREADY CARRIES THE SETTERS — and this list re-typed EIGHT of them
# anyway (switch, hide, unlist, unpublish, share, disable, remove, drop), which is
# proof the explicit half was written without reading the spliced half. Harmless
# to the regex; not harmless as evidence, because the same habit is what left
# `link` in here and nowhere else, where its veto can never fire.
# ⛔⛔ TWO HALVES, BECAUSE TWO DIFFERENT QUESTIONS READ THIS. The NEGATION veto
# wants every verb — `stop trying to fetch the podcast` FETCHED IT until the read
# verbs were added. The COMPOUND-ASK test wants only the verbs that CHANGE
# something: a trailing read request is a follow-up and is trimmed, a trailing
# MUTATION is a second command and the message has to go to the catch-all.
# Spelled as one list, the compound test would refuse `stop the tesla run and show
# me the rest`, which 1.1 deliberately made work.
_MUTATING_VERBS = (rf"(?:{_VIS_SETTERS[3:-1]}|{_VIS_HIDE_ALL[3:-1]}|"
                   rf"{_VIS_PUBLISH_ALL[3:-1]}|"
                   rf"send|pair|add|connect|link|unlink|forget|delete|unpair|"
                   rf"pause|resume|unpause|retry|stop|end|abort|cancel|skip|"
                   rf"approve|accept|allow|grant|deny|refuse|reject|block|"
                   rf"research|look\s+into|investigate|start|run|use|update|install|"
                   rf"uninstall|reset|rename|sign\s+out|log\s+out|logout|"
                   rf"switch\s+to|ask|request|borrow|apply)")
# ⛔ THE READ VERBS. `don'?t ask to use the Lab Mac` still offered to hand the
# owner the person's name and email, because the ask surface was missing entirely.
_READING_VERBS = (r"(?:fetch|get|show|list|tell|display|download|open|play|"
                  r"status|check)")
_ACT_VERBS = rf"(?:{_MUTATING_VERBS[3:-1]}|{_READING_VERBS[3:-1]})"
# ⛔⛔ ONE POLARITY LIST. There were TWO — this one and the inline list inside
# `_NEG_PUBLISH_SIDE` — and neither derived from the other: this one had
# private/hidden/unlisted/invisible the other lacked, the other had offer/offering
# this one lacked. Nothing reconciled them and nothing ever would have.
_POLARITY_WORDS = _alt(_PUBLISH_POLARITY_WORDS + _HIDE_POLARITY_WORDS)
_NEG_BEFORE_VERB = re.compile(rf"\b{_NEG_WORDS}\b{_NEG_FILLER}\s+{_ACT_VERBS}\b", re.I)
# ⛔⛔⛔ A NEGATOR INSIDE A NOUN PHRASE BELONGS TO THE NAME, and position relative
# to the DETERMINER is what separates the two — not distance, which is what I
# tried first. `make my Now or Never Mac public` has its negator AFTER `my`,
# inside the noun phrase, and it hid the machine; `I do not want my computer to be
# public` has its negator BEFORE the determiner, in the verb group, and it is a
# real negation. Both put a machine noun between the negator and `public`, so no
# adjacency or noun-distance rule can tell them apart. The determiner can.
# ⭐ THE DETERMINER IS KEPT and only the negator dropped, so the noun phrase still
# parses for every capture downstream.
# ⛔ AND IT MUST NOT EAT A POLARITY NEGATION. `make my mac not private` matches
# "determiner + one token + negator" exactly as a name does — so blanking here
# sent it back to executing a hide, the very defect this block exists to fix. A
# negator followed by a POLARITY word is never part of a machine's name.
_NEG_IN_NAME = re.compile(
    rf"(\b(?:my|the|your|our|their|its|his|her|a|an)\s+(?:[\w'-]+\s+){{0,3}})"
    rf"{_NEG_WORDS}\b(?!\s+(?:be\s+|being\s+|stay\s+|remain\s+)?{_POLARITY_WORDS}\b)",
    re.I)
# ⛔⛔⛔ AND THE TWO DIRECTIONS ARE NOT SYMMETRIC. THIS IS THE THING I GOT WRONG,
# and the existing suite caught it: **negating a PUBLISH names a concrete act —
# a hide — while negating a HIDE names nothing.**
#   `no longer share my mac`                  = hide it.        Two tests demand it.
#   `I do not want my computer to be public`  = hide it.
#   `don'''t make my mac public`                = hide it.
#   `don'''t hide my mac`                       = ??? leave it? publish it? -> catch-all.
# That asymmetry is exactly why this file'''s original negation arm only ever
# looked for PUBLIC-side words, and my first veto flattened it and broke both
# phrasings. The wide span is safe here now that name-internal negators are gone.
# ⛔ A COPULA IN FRONT OF THE NEGATOR MAKES IT A STATEMENT OF STATE, NOT A REQUEST.
# `my computer is not listed` came back EXECUTING a hide — the person was telling
# the client what they already see, or asking about it, and the answer was to act.
# HEAD showed them their devices, which is right.
_NEG_PUBLISH_SIDE = re.compile(
    rf"(?<!\bis )(?<!\bare )(?<!\bwas )(?<!\bwere )(?<!\bisn't )(?<!\baren't )"
    # ⛔⛔ THE SECOND POLARITY LIST — and it had `offer`/`offering` the first one
    # lacked while lacking the hide words the first one had. Deriving it caught a
    # live regression the moment the publish gerunds entered the act-verb list:
    # `no longer publishing my mac` became a NEGATED COMMAND and reached the
    # catch-all, because `publishing` was in one list and not the other. It means
    # "stop publishing it" — a hide — and this is the test that says so.
    # ⛔⛤ AND `let <people> find` IS A PUBLISH IN THIS LIST TOO. The moment that
    # phrasing got a signal — it is the one SKILL.md teaches — its NEGATION
    # inverted: `don't let people find my mac` reached the publish CONFIRM, the
    # exact opposite of the ask. A new signal owns its own negation; 1.1's rule
    # says negating a publish is a concrete hide, and that is where it lands now.
    rf"\b{_NEG_WORDS}\b[^.?!]{{0,40}}\b(?:{_alt(_PUBLISH_POLARITY_WORDS)[3:-1]}|"
    rf"{_VIS_PUBLISH_ALL[3:-1]}|"
    rf"let\s+(?:people|persons|users|anyone|anybody|everyone|everybody|others|"
    rf"strangers|folks|other\s+(?:people|persons?|users?))\s+"
    rf"(?:find|see|discover|locate))\b", re.I)
_NEG_BEFORE_POLARITY = re.compile(
    rf"\b(?:not|no\s+longer|never)\s+(?:be\s+|being\s+|stay\s+|remain\s+)?"
    rf"{_POLARITY_WORDS}\b", re.I)


def _negated_command(text: str) -> bool:
    """True when the message NEGATES the act it names — the catch-all is the landing.

    ⛔ QUOTED NAMES ARE BLANKED FIRST, so a machine called "Don'''t Panic PC" cannot
    veto its own request, and so the escape every residue in this file offers
    applies here too.
    ⛔ AN INVERTED POLARITY IS NOT A VETO. `make my mac not private` names a real
    act — publishing — so it must reach the visibility branch, not the catch-all.
    """
    bare = _NEG_IN_NAME.sub(r"\1", _outside_quoted_names(text or ""))
    # `not private` is a PUBLISH — a real act, so it must reach its branch.
    # ⛔⛔ BUT NOT WHEN A NEGATOR ALSO PRECEDES THE VERB. A MUTATION SURVIVOR FOUND
    # THIS: `don'''t make my mac not private` and `never make my mac not private` are
    # DOUBLE negations, and with the bare test they reached a PUBLISH confirm —
    # the opposite of what the person asked, on a surface where one "yes" makes a
    # machine findable by strangers. The conjunct was in my first draft and I
    # dropped it when the publish-side asymmetry went in; nothing but the harness
    # noticed. The landing for a double negation is the catch-all, like every
    # other negation this file cannot resolve to one act.
    if _NEG_BEFORE_POLARITY.search(bare) and not _NEG_BEFORE_VERB.search(bare):
        return False
    # `don't share` / `no longer public` is a HIDE — also a real act.
    if _NEG_PUBLISH_SIDE.search(bare):
        return False
    return bool(_NEG_BEFORE_VERB.search(bare))


# ⛔⛔ MATCHED PAIRS, NOT ANY TWO OF THE SIX QUOTE CHARACTERS — and this file had
# already written the warning I ignored. `_NL_QUOTED_RE` says, in as many words,
# that apostrophes are NOT delimiters because a contraction plus a possessive
# would extract the garbage between them. I used `_NL_QUOTE_CHARS`, which
# contains both apostrophes, so TWO CONTRACTIONS made a quoted span: `don't hide
# all my computers, it's fine` blanked down to "don s fine", the set vanished,
# and the unconfirmed hide RAN — the exact defect this wave exists to close,
# reintroduced by the line that grants the escape from it. A mutation survivor is
# what found it.
# ⭐ `‘…’` STAYS A PAIR because the picker's own copy uses curly singles on
# phones. A contraction cannot forge one: the apostrophe people type is the
# straight `'` or the curly RIGHT `’`, and neither of those opens this span.
_SET_QUOTED_SPAN = re.compile(r'"[^"]*"|“[^”]*”|‘[^’]*’')


def _outside_quoted_names(text: str) -> str:
    """The message with every quoted span blanked out.

    ⛔⛔ QUOTING A NAME EXEMPTS IT OUTRIGHT, and this is the only rung that can
    give a person an escape from the residue above. It also restores three run
    titles 7.9-5 ate — `stop "All Reports"`, `stop "Every Report"` — because the
    signal is looked for in what is LEFT once the name is removed.
    ⛔ THE SPAN IS BLANKED, NOT DELETED. Dropping it would weld the words either
    side of the name into a phrase nobody typed.
    """
    return _SET_QUOTED_SPAN.sub(" ", text or "")


# ⛔ THE EXCLUSION SHAPES ARE CLAUSE-BOUNDED, NOT WILDCARDS. Each runs to the next
# comma, semicolon or full stop — an unbounded span is how 7.9-5's filler ate real
# names, and nothing in this wave gets to reintroduce one.
# ⛔ `but` WAS MISSING, AND IT IS THE COMMONEST EXCLUSION WORD IN ENGLISH.
# `approve everyone but Sam` and `hide all my computers but the Studio PC` name a
# set MINUS one, and with `but` absent the exclusion never blanked, so the set
# signal fired on the whole phrase and the one named exception was thrown away.
# ⛔⛔ AND `not` ONLY EXCLUDES WHEN IT OPENS A CLAUSE. `hide my computers and my
# Not Ready PC` had "Not Ready PC" blanked as an exclusion, which left the plural
# without its head and EXECUTED an unconfirmed hide on a set. Bare `not` was
# pre-existing, but removing `and` from the head test is what turned it into a
# hole — two safe-looking edits composing into one live defect.
_SET_EXCLUSION = (r"(?:(?:(?<=,)|(?<=;)|(?<=\band)|(?<=\bbut)|(?<=^))\s*\bnot\b[^,.;]*"
                  r"|\b(?:except|excluding|apart\s+from|other\s+than|"
                  # ⛔ BARE `but` WAS TOO WIDE AND I CAUGHT IT IN MY OWN TEST
                  # RUN. `hide my mac but also my pc` had its second machine
                  # blanked away as an "exclusion", leaving one target and an
                  # unconfirmed hide. `but` excludes only when it NEGATES;
                  # `but also` is a conjunction and is listed as one.
                  r"rather\s+than|instead\s+of|but\s+not|but\s+leave|"
                  r"but\s+don'?t)\b[^,.;]*"
                  r"|\bleave\b[^,.;]*\balone\b)")


# ⛔⛔ TWO MORE CLAUSES THAT ARE NOT SETS, BOTH MEASURED AS MY OWN FALSE POSITIVES.
# · THE PUBLISH AUDIENCE. `make my mac public to everyone` came back "I publish one
#   computer at a time" — but `everyone` there is WHO CAN SEE IT, and publishing is
#   inherently to everyone; exactly ONE machine was named. The audience is a
#   property of the verb, never a count of its objects.
# · A READ-ONLY FOLLOW-UP QUESTION. `stop the tesla run and show me the rest` came
#   back refused because `the rest` is a collective — but the `and` is not nominal
#   at all: one run was named and then a SECOND, read-only thing was asked. The
#   tell is a READ VERB after the conjunction. `hide my computers and list them`
#   is still a set, because the plural signal fires on what is LEFT.
# ⛔ `everyone` IS THE AUDIENCE, NOT A SET OF MACHINES — and the exemption used to
# require a POLARITY word in front of it, so `make my mac public to everyone` was
# exempt while `offer my Studio PC to everyone` was refused as a bulk publish.
# The publish VERBS carry the same meaning as the polarity words here, and they
# are derived rather than re-listed.
_SET_AUDIENCE_WHO = (r"(?:everyone|everybody|anyone|anybody|all|the\s+world|"
                     r"the\s+public|other\s+people|strangers)")
_SET_AUDIENCE = (rf"\b(?:public(?:ly)?|findable|discoverable|visible|available|open"
                 rf"|{_VIS_PUBLISH_ALL[3:-1]})\s+"
                 rf"(?:it\s+|them\s+|this\s+)?to\s+{_SET_AUDIENCE_WHO}\b")
# ⛔⛝ A READ VERB IS NOT ENOUGH — IT NEEDS A QUESTION'S OBJECT AFTER IT. Without
# that, `hide my Show and Tell PC` had "and Tell PC" eaten as a read tail and
# EXECUTED a hide on a machine called "Show", and `pause the Show and Tell
# research` paused a run called "Show". That is the trim-eats-a-real-name class
# this wave exists to close, reintroduced by this wave's own new trim.
# ⭐ A follow-up question names WHO it is for: show ME, list THEM, tell me THE
# REST. A machine name never does.
_SET_READ_TAIL = (r"(?:\s*,\s*|\s*;\s*|\s+and\s+|\s+then\s+)(?:also\s+)?"
                  r"(?:show|list|tell|display|give|name)\s+"
                  r"(?:me|us|them|it|myself)\b[^.?!]*$"
                  r"|(?:\s*,\s*|\s*;\s*|\s+and\s+|\s+then\s+)(?:also\s+)?"
                  r"(?:what|which|who)\b[^.?!]*$"
                  r"|(?:\s*,\s*|\s*;\s*|\s+and\s+|\s+then\s+)(?:also\s+)?"
                  r"(?:show|list|tell|display|give|name)\s+"
                  r"(?:the\s+rest|the\s+others|everything\s+else)\b[^.?!]*$")


def _outside_exclusions(text: str) -> str:
    """The message with quoted names, exclusion clauses, the publish AUDIENCE and a
    trailing READ-ONLY question all blanked out."""
    bare = _outside_quoted_names(text)
    bare = re.sub(_SET_READ_TAIL, " ", bare, flags=re.I)
    bare = re.sub(_SET_AUDIENCE, " ", bare, flags=re.I)
    # ⛔⛤ AND `to everyone` IS AN AUDIENCE AFTER A PUBLISH VERB TOO, not only
    # after a polarity word. `make my mac public to everyone` was exempt and
    # `offer my Studio PC to everyone` was REFUSED as a bulk publish — the same
    # sentence, the same audience, two answers.
    # ⛔ ONLY THE `to <who>` IS BLANKED, never the span from the verb. Blanking
    # that whole span would erase the name as well, and `offer all my macs to
    # everyone` — a genuine set — would come out exempt. This is the 40-character
    # window 1.1 had to remove, and it is not coming back.
    if re.search(rf"\b{_VIS_PUBLISH_ALL}\b", bare, re.I):
        bare = re.sub(rf"\bto\s+{_SET_AUDIENCE_WHO}\b", " ", bare, flags=re.I)
    return re.sub(_SET_EXCLUSION, " ", bare, flags=re.I)


# ⛔⛔ A COMPOUND ASK LOSES HALF OF ITSELF SILENTLY, AND THAT IS WORSE THAN A
# REFUSAL. Measured three times across 1.1 and 1.2: `pause the run and switch to
# the office PC` PAUSED a run called “run and switch to the office PC” and dropped
# the switch; `stop the tesla run and hide my mac` offered to stop a run called
# “tesla run and hide my mac”. The person asked for two things and watched one
# happen to a name they never said.
# ⛔ A TRAILING READ REQUEST IS NOT A SECOND COMMAND — `stop the tesla run and
# show me the rest` is one ask with a follow-up, and 1.1 deliberately made it
# work. Only a MUTATION on the far side of the conjunction makes a message
# compound, which is why the verb list is split above.
# ⛔⛔ AND IT IS NARROW, BECAUSE MY FIRST VERSION WAS NOT AND THE A/B SAID SO:
# written as "any mutation on the far side of a conjunction", it refused FOUR
# real phrasings — `skip the video and drop claude` (one ask, two phases),
# `hide my mac and make it private` (one ask said twice), and
# `find a public one and ask its owner for access`, which is a phrasing SKILL.md
# itself teaches. Two halves of the SAME act are one ask.
# ⭐ The measured defects were one shape and one only: RUN CONTROL followed by a
# DEVICE command. That is what this refuses, and nothing wider until something
# wider is measured.
_COMPOUND_ASK = re.compile(
    r"\b(?:stop|end|abort|cancel|pause|resume|unpause|retry)\b[^.?!]*?"
    r"\s+(?:and|then|also|plus|,\s*and|;)\s+(?:please\s+|also\s+)?"
    # ⛔⛤ AND IT DOES NOT SPLICE THE SETTER LIST, WHICH IS THE FILE'S OWN POINT
    # ABOUT THAT LIST: it is a TARGET list, not a signal one. Splicing it here
    # made `take`, `put`, `set`, `turn`, `drop` and `make` count as second
    # commands, so 56 ordinary follow-ups were refused — `stop the run and take
    # a break`, `pause the run and put it on hold`, `stop the run and drop me a
    # link`. Only a DEVICE command makes a message compound.
    # ⛔ `drop` IS NOT IN THE SECOND-VERB LIST EITHER. It is the three-way
    # ambiguous one, and `stop the run and drop me a link` is an idiom, not a
    # device command.
    rf"(?:switch\s+to|use|run\s+(?:it|everything)\s+on|remove|unlink|forget|delete|"
    rf"{_VIS_HIDE_ALL[3:-1]}|{_VIS_PUBLISH_ALL[3:-1]})\b",
    re.I)


def _is_compound_ask(text: str) -> bool:
    """Two commands in one message — the landing is the catch-all, never half.

    ⛔⛤ AND A RUN TITLE IS BLANKED FIRST, not only a quoted one. `stop the Pause
    and Share run` is ONE ask about a machine-shop's run; 16 driven titles were
    refused because the conjunction inside the NAME read as a second command,
    and quoting was the only escape. The explicit run-naming spans are the ones
    the skip capture already recognises.
    """
    bare = _outside_quoted_names(text or "")
    bare = re.sub(r"\bthe\s+[\w'\u2019 -]+?\s+(?:run|research)\b", " the run ", bare, flags=re.I)
    bare = re.sub(r"\b(?:on|for|in|of)\s+(?:the\s+|my\s+)?[\w'\u2019 -]+?\s+(?:run|research)\b",
                  " on the run ", bare, flags=re.I)
    return bool(_COMPOUND_ASK.search(bare))


def _trim_trailing_clause(name: str, whole_message: str = "") -> str:
    """⛔⛔ A QUOTED NAME IS TAKEN VERBATIM — pass the whole message and the trims
    are skipped when the capture IS the quoted span. Cross-verify measured that
    the escape hatch this wave promised worked at ONE capture site of six, and
    even there it tested the matched PATTERN's group count rather than whether
    anything had been quoted — so `pause “Not Today”` captured “Not” and paused
    a DIFFERENT run, and `stop sharing "Studio PC Now"` was trimmed anyway.
    Quoting is the one thing a person can do to be unambiguous; it has to work
    everywhere or it is not an escape hatch."""
    if whole_message:
        q = _quoted_name(whole_message)
        if q and (name or "").strip().strip(_NL_QUOTE_CHARS).strip() == q.strip():
            return q.strip()
    return _trim_trailing_clause_inner(name)


def _trim_trailing_clause_inner(name: str) -> str:
    """A captured NAME with a trailing read-only question or exclusion removed.

    ⛔⛔ ONE COPY, CALLED FROM EVERY CAPTURE THAT NEEDED IT. The visibility branch
    already trimmed exclusions and no other branch did, which is how
    `stop the tesla run and show me the rest` came to quote
    "tesla run and show me the rest" back as a run title. It ships here because
    the read-tail blanker above made these phrases ACT instead of being wrongly
    refused, and acting on a welded name is not an improvement on refusing.
    ⛔ IT NEVER RETURNS EMPTY. A trim that eats the whole name sends the command
    to the picker, which is the unconfirmed-wrong-target outcome these branches
    exist to avoid — the 7.9-5b lesson, measured on `Not My Mac`.
    """
    whole = (name or "").strip()
    out = re.sub(_SET_READ_TAIL, "", whole, flags=re.I).strip()
    out = re.sub(rf"\s*(?:,|;|\band\b)\s*{_SET_EXCLUSION}\s*$", "", out, flags=re.I).strip()
    # ⛔ AN AUDIENCE IS NOT A NAME EITHER. `share my Studio PC with other people`
    # captured the whole tail, which then matched the about-other-people test and
    # BLANKED the capture — so naming the audience cost you the machine and the
    # publish fell to the picker. The audience is who, not which.
    out = re.sub(r"\s+(?:with|to|for)\s+(?:other\s+(?:people|persons?|users?)|"
                 r"everyone|everybody|anyone|anybody|strangers|the\s+world|"
                 r"the\s+public|all)\b.*$", "", out, flags=re.I).strip()
    # ⛔⛔ AND THE POLITENESS COMES OFF TOO — WAVE 1.2 MEASURED 592 PHRASINGS
    # BROKEN BY ONE COURTEOUS WORD. `hide my mac please` captured “mac please”,
    # which resolves to nothing, so a command that worked without the word
    # REFUSED with it. The words are the same ones `_SET_HEAD` already uses to
    # decide where a name ends; they are derived from it, not written again.
    # ⛔ REPEATEDLY, because people stack them: “hide my Studio PC now, thanks”.
    # ⛔ AND IT STILL NEVER RETURNS EMPTY — the guard below is why a machine
    # actually called “Please” survives. A machine called “Studio PC Now” does
    # not, and must be QUOTED; that cost is real and is the accepted trade,
    # because today every one of those phrasings refuses outright.
    for _ in range(4):
        # A comma-separated tail comes off whatever it leaves behind.
        commaed = _NAME_TAIL_COMMAED.sub("", out).strip()
        if commaed and commaed != out:
            out = commaed
            continue
        # ⭐ AND NO BARE-NOUN GUARD IS NEEDED HERE. The space pattern trims only
        # the words nobody is called, so `hide my mac please` SHOULD come out as
        # the bare noun and reach the picker — that is the fix, not a loss. The
        # words a machine can genuinely end in are comma-gated above.
        stripped = _NAME_TAIL_SPACED.sub("", out).strip()
        if stripped == out or not stripped:
            break
        out = stripped
    out = re.sub(r"[\s,;]+$", "", out).strip()
    return out or whole


def _names_a_set(text: str) -> bool:
    """True when this names a SET of machines, runs or waiting people.

    Three signals, each on the surface it is the only one that can serve —
    measured, not assumed:

    · a PLURAL machine or run noun. The signed signal, and it carries the
      machine surfaces on its own: `my computers`, `my two macs`,
      `any of my computers`.
    · a QUANTIFIER BINDING A SINGULAR noun through the determiner slot.
      `hide every computer` and `every computer i have` use the singular form,
      so the plural test is blind to them.
    · a COLLECTIVE OF PEOPLE. ⛔⛔ THE CONSENT SURFACE HAS NO MACHINE NOUN AT ALL
      — the set there is of PEOPLE — so the signed signal missed the whole queue:
      `approve them all`, `approve the queue`, `let them all in`, `refuse
      everyone` and the entire deny mirror, the branch that arms a seven-day
      refusal. It matters more than the rest: those phrases capture NOTHING, and
      `_resolve_asker("")` returns the sole waiting row, so one stranger is let
      in — or one person refused for a week — while the person believes they
      answered the queue.
    """
    bare = _outside_quoted_names(text)
    return any(s.search(bare) for s in _SET_SIGNALS)


def _request_names_a_set(message: str, captured: str | None = None) -> bool:
    """The rule every ACT branch asks, about what THAT branch is going to do.

    ⛔⛔ IT READS THE MESSAGE, BECAUSE ONLY THE MESSAGE STILL HAS THE QUOTES. A
    captured name arrives stripped of them, so testing the capture would refuse
    `stop "All Reports"` and `remove "All My Laptops"` — and quoting is the one
    escape this design offers from the plural-NAME residue.

    ⛔⛔ AND THE CAPTURE IS NOT THE OVERRIDE. I built it as one first: a branch
    that captured a non-set name won over the message. It looked right on the two
    phrases it was written for and it silently DEFEATED FOUR REAL SETS, because on
    those the capture is a FRAGMENT OF the set phrase, not a name beside it —
    `approve the queue` captures "queue", `approve the rest` captures "rest",
    `stop all my research on tesla` captures "tesla". Each came back a confident
    single-target confirm. The A/B against the pre-build revision is what showed
    it; the predicate itself was 44/44 either way.

    ⭐ WHAT ACTUALLY SEPARATES THE TWO PHRASES 7.9-5 GOT WRONG IS AN EXCLUSION.
    `make my Studio PC public, not all my devices` and `hide the Studio PC and
    leave all my other machines alone` both name one target and then say which
    set to leave out. So an exclusion clause is blanked with the quoted names, and
    a set mentioned only inside one does not count. `captured` is accepted and
    deliberately unused for the decision — see the assertion in the tests.
    """
    return _names_a_set(_outside_exclusions(message))


def _is_bare_machine_noun(name: str) -> bool:
    """True when what a rule captured as a NAME is only the word for a machine.

    ⛔⛔ THE LEADING-NOUN STRIP CANNOT CATCH THIS ONE, and widening the noun list
    is what exposed it. The strip removes "mac " from "mac LABPC001"; it leaves
    "mac" alone because there is nothing after it to be the name. So "remove my
    mac" — with the wider list — captured "mac" and offered to unlink a machine
    called “mac”, a DESTRUCTIVE confirm whose own follow-up resolves to "No device
    matching “mac”". It is the same defect 7.9-3 fixed for "remove device
    LABPC001", one rung further in.

    ⛔ `phones?` IS HERE AND NOT IN `_MACHINE_NOUNS`. The unlink rule admits it as
    a thing people SAY — "remove my phone" — while nothing in this product is a
    phone, so it can never be a name either. Leaving it out let exactly that
    sentence through to the destructive confirm.

    ⛔ A person who literally named a computer "Mac" now gets asked which one
    instead of a confirm. That is the trade this makes on purpose: the cost is one
    extra question, and the cost of the other reading is unlinking the wrong
    machine on a "yes".
    """
    # ⛔⛔ AND A BULK PHRASE NAMES NOTHING EITHER. "remove all my devices" captured
    # "all my devices" and offered to unlink a machine called “all my devices” —
    # a DESTRUCTIVE confirm on a request this product cannot carry out at all,
    # since unlink takes exactly one machine. At HEAD the list clause answered it
    # first; the action gate this wave added handed it to the remove branch.
    return bool(re.fullmatch(
        rf"(?:(?:all|every|each|both)\s+(?:my\s+|the\s+|of\s+my\s+)?)?"
        rf"(?:{_MACHINE_NOUNS_SAID})", (name or "").strip(), re.I))


# ⛔⛔ THE SET-REQUEST GATE LIVED HERE AND WAS REVERTED ON 2026-09-09, OWNER'S
# CALL, AFTER CROSS-VERIFY MEASURED IT AS A REGRESSION. It classified a captured
# name by its QUANTIFIER, and a wildcard word slot made any real machine name
# shaped `<all|every|each|both> <word> <machine-noun>` full-match the bulk
# pattern — 96 measured phrases, 12 names × 8 verbs, so "All Hands Mac" could
# not be unlinked, published, hidden, asked for, approved or denied, while
# `switch to All Hands Mac` still resolved it.
#
# ⭐ IT RETURNS AS WAVE 7.9-5b WITH A DIFFERENT SIGNAL: a request names a set
# iff it carries a PLURAL machine/run noun outside a quoted name. "All Hands
# Mac" is singular and survives; `my computers`, `my two macs` and `any of my
# computers` — all of which the quantifier design MISSED — do not. WAVES.md
# holds the full finding list; nothing about it is carried here.
#
# ⛔ 7.9-4's unlink gate below is UNCHANGED and stays. It was never the problem.
_NL_QUOTE_CHARS = "“”‘’\"'"

# ⛔ A PAIRED span, never a character class. See the visibility capture for what
# a class cost. One group, so every user reads `.group(1)` the same way.
_QUOTED_SPAN = r"(?:\"([^\"]+)\"|“([^”]+)”|‘([^’]+)’)"
_QUOTED_RE = re.compile(_QUOTED_SPAN)


def _quoted_name(text: str) -> str:
    """The PAIRED quoted span in a message, taken verbatim, or "".

    ⛔⛔ CHASING A MUTATION SURVIVOR FOUND THIS, AND IT WAS MINE. Stripping quote
    characters off the EDGES of a capture works only while the quote IS the edge:
    `switch to “Nodes Mac”, thanks` has a tail after the closing quote, so the
    opening `“` came off, the closing `”` did not, and the leading-noun strip then
    ate `Nodes` and handed the lookup `Mac”` — which matched two machines. The
    visibility branch had already been taught to pair its quotes; these two had
    not, and a quoted name is the one thing a person can do to be unambiguous.
    """
    return _cap(_QUOTED_RE.search(text or ""))


def _cap(m: "re.Match | None") -> str:
    """The first non-empty group of a match.

    ⛔ `_QUOTED_SPAN` carries THREE alternatives, so a capture that used to be
    `group(1)` is now whichever of the three matched. Every reader goes through
    here so a fourth quote style can be added in one place — and so that a
    straight-quoted name and a curly-quoted one cannot diverge again.
    """
    return next((g for g in (m.groups() if m else ()) if g), "")

_NL_CONFIRMS = {
    "stop": "Stop {name}? It ends the run — everything finished so far is kept. Say yes and I’ll stop it.",
    "logout": "Sign out of Super Research? (The skill stays installed — you can sign back in anytime.) Say yes and I’ll sign you out.",
    "device-remove": "Unlink {name}? It keeps running, but its access code changes — the old one stops working and I’ll show you the new one. Say yes and I’ll remove it.",
    "update": "Update the Super Research skill (this chat runtime)? The bridge restarts briefly. Say yes and I’ll update it.",
    # ⭐ OPENS WITH THE PAGE (owner, 2026-09-24). Only an explicit "install it
    # here / on this machine" reaches this confirm now, and a yes installs on the
    # machine the chat runs on — so the page, which sets up ANY computer, is named
    # before the offer.
    "install": (f"The setup steps are at {_INSTALL_PAGE_URL}. Install the Super "
                "Research backend on the connected device — the one this chat runs "
                "on — now? Say yes and I’ll set it up."),
    # ⛔⛔ CONFIRM-GATED THOUGH IT DESTROYS NOTHING, and that is the point. It is
    # the only verb on this surface that hands the person's NAME AND EMAIL to a
    # stranger, spends one of five asks an hour, and arms a week-long refusal if
    # the answer is no. The web app will not let anybody ask without showing them
    # three lines first; without this the chat path would be the one door into the
    # feature with no consent moment at all.
    # ⛔⛔ THREE FACTS, IN THE WEB APP'S OWN ORDER, and the first draft carried
    # none of them properly. It said the owner would see "your name and email
    # address" — they see the name, and the email only when no name is set — and
    # it left out the two disclosures that cost the reader most: the research
    # RUNS on somebody else's computer using THEIR paid AI accounts, and that
    # computer can read the research in this account. Cross-verify caught it
    # against `BrowsePublicDevicesModal` and `requesterLabelOf`.
    "device-ask": "Ask the owner of {name} to let you use it? Your research would "
                  "run on their computer, using their ChatGPT, Gemini and Claude "
                  "accounts; that computer can read the research in your account; "
                  "and they see your name — or your email, if you haven’t set one. "
                  "They decide, and nothing runs on it unless they say yes. Say yes "
                  "and I’ll ask.",
    # ⛔⛔ THE WEB APP DOES NOT CONFIRM THIS AND THIS SURFACE MUST. Over there the
    # warning sits at the top of the list the Yes and No buttons are in, so the
    # cost is on screen at the moment of the tap. Here there is no screen — the
    # confirm line IS that warning, and it carries the app's own sentence rather
    # than a second wording of it.
    "device-approve": "Say yes to {name}? Anyone you say yes to can run research "
                      "on that computer — the same as somebody you gave an "
                      "access code to. Say yes and I’ll tell them yes.",
    # ⛔⛝ DENYING CONFIRMS TOO, AND ITS COST IS THE ONE NOBODY IS TOLD. A refusal
    # stops that person asking again for a week; the app tells THEM that and
    # tells the owner nothing at all — the fact lives in a code comment there.
    # It is recoverable (the access code still works) and that is said here,
    # because a cost with no way out reads as a bigger decision than it is.
    "device-deny": "Say no to {name}? They cannot ask again for a week — the app "
                   "tries to tell them, but that depends on their own "
                   "notification settings. Giving them the access code still works "
                   "if you change your mind. Say yes and I’ll turn them down.",
    # ⛔⛔ ONLY THE PUBLIC DIRECTION. Hiding a computer takes it OFF a list and
    # costs nothing anybody was promised; confirming a strictly narrowing change
    # is how people learn to click through the confirms that matter.
    # ⛔ THE NAME IT PUBLISHES IS THE DISCLOSURE. A Mac nobody has renamed
    # reports a hostname carrying its owner's own name, so this says so without
    # needing to know the value — the command prints the exact label after.
    "device-visibility": "Let other people find {name} and ask to use it? They "
                         "would see the name it reports — on a computer nobody "
                         "has renamed that is often its owner’s own name — and "
                         "you would still approve every person yourself. Say yes "
                         "and I’ll switch it on.",
}


# Info-only reply (NOT a confirm — there's no action for me to take): the skill
# only updates itself. A backend-update ask is redirected to where it happens —
# `superresearch --update` on the Research computer OR the app's update surface.
_NL_BACKEND_UPDATE_MOVED = (
    "I only update the Super Research skill (this chat) from here. To update Super "
    "Research on your Research computer, run “superresearch --update” there, or update "
    "it from the app (Settings → About, or the update notification). "
    "(Say “update” to update this skill.)"
)


def _nl_run_name(t: str, verb_tail: str = "") -> "str | None":
    """A run name from free text: a quoted title wins; else the words after
    of/for/on/about (minus articles + 'run/one/research' tails). Generic
    references ('it', 'the run') → None → the command defaults to the
    most-recent run."""
    m = _NL_QUOTED_RE.search(t)
    name = None
    if m:
        name = m.group(1)
    else:
        src = verb_tail if verb_tail else t
        # ⛔ `for me` IS NOT A RUN TITLE. `resume the Mars run for me` came out
        # naming a run “me”, because `for` is one of the title prepositions.
        m2 = re.search(r"\b(?:of|for|on|about)\s+(?:the\s+|my\s+)?"
                       r"((?!(?:me|us|you|him|her|them|now|today)\b).+)$", src, re.I) or \
            (re.search(r"^(?:the\s+|my\s+)?(.+)$", verb_tail, re.I) if verb_tail else None)
        if m2:
            name = m2.group(1)
    if not name:
        return None
    name = re.sub(r"[?.!,]+$", "", name).strip()
    # ⛔ A TRAILING READ-ONLY QUESTION IS NOT PART OF THE TITLE.
    name = _trim_trailing_clause(name, t)
    name = re.sub(r"\s+(run|one|research|research run)$", "", name, flags=re.I).strip()
    if not name or name.lower() in _NL_GENERIC_RUN:
        return None
    return name


# ⭐⭐ "LOGGED IN?" IS A QUESTION ABOUT THE ACCOUNT (owner, 2026-09-25) — rule 2.
# Both are FULL matches over the whole message, so a research topic that merely
# contains the words ("research login status pages") is never taken for one.
# `ask` / `tail` let rule 2 tell a question ("are you logged in", "logged in yet")
# from a statement ("signed in" after a link — the person saying they did it).
_NL_SIGNIN_QUESTION = re.compile(
    r"(?:so |and |ok |okay |well |hey )?"
    r"(?P<ask>am i |are (?:you|we) |is (?:it|this|the agent|the skill|super ?research) )?"
    r"(?:(?:now|already|still|all) )?"
    r"(?:signed|logged)[ -]?in(?:to)?"
    r"(?: (?:to )?(?:super ?research|sr|the app|my account))?"
    r"(?: (?P<tail>yet|now|already|ok|okay|properly|successfully))?")
_NL_LOGIN_CHECK = re.compile(
    rf"{_NL_LEAD_IN}(?:"
    r"(?:what'?s |what is )?(?:my |the )?(?:log ?in|sign[ -]?in) status"
    r"|check (?:on )?(?:my |the )?(?:log ?in|sign[ -]?in)(?: status)?"
    r"|(?:did (?:the |my )?(?:log ?in|sign[ -]?in|logging in|signing in) "
    r"(?:work|go through|succeed|complete|finish)"
    r"|(?:has|is) (?:the |my )?(?:log ?in|sign[ -]?in) (?:worked|done|complete|completed"
    r"|finished|gone through|succeeded|working|ok|okay))(?: [^.?!]{1,40})?"
    r")(?: (?:yet|now|please|for me))?")


def _nl_resolve(text: str) -> "tuple[list[str] | None, list[str] | None]":
    """Map a verbatim user message to (argv, None) to execute, or
    (None, user-safe lines) to relay. Ordered — most specific first."""
    t = " ".join((text or "").split())
    low = t.lower().rstrip("?!. ")
    if not low:
        return None, ["What would you like? I can research a topic, check a run’s "
                      "status, fetch its podcast or links, or manage your devices."]

    # 0. ⛔⛔ A NEGATED COMMAND NEVER REACHES ITS OWN VERB. It sits above every act
    #    branch because the failure was not one branch missing a veto — it was
    #    EIGHT, and a negation that got past one of them REROUTED into another
    #    (`don'''t research the pause feature` came back as a PAUSE). The landing is
    #    the catch-all, which is this file'''s own decision where the negation
    #    vocabulary was first written: guessing which opposite the person meant is
    #    worse than asking. Measured: 81 of 112 negated forms reached the action.
    if _negated_command(t):
        return None, [_NL_CATCH_ALL]

    # 1. An access code = pair a device (never a secret — see SKILL.md). Wins
    #    only when the message IS the code, or says device/pair/add/code — a
    #    code-shaped token inside a sentence ("research iphone17 pricing")
    #    must not hijack the request into a bogus pairing attempt.
    code_m = _NL_CODE_RE.search(t)
    if code_m:
        tok = code_m.group(1) or code_m.group(2)
        _kw = re.search(rf"\b({_MACHINE_NOUNS}|pair|add|code)\b", low)
        _bare = re.fullmatch(r"[^A-Za-z0-9]*" + re.escape(tok) + r"[^A-Za-z0-9]*", t, re.I)
        # ⛔⛔ A VERB THAT NAMES AN EXISTING COMPUTER IS NOT A PAIRING. The comment
        # above claims a code-shaped token inside a sentence cannot hijack the
        # request, and the device keyword was the whole guard — so "switch to the
        # machine LABPC001" carried BOTH and came back "That code didn't match any
        # device", refusing a switch as a bad code. Reproduced against this
        # resolver.
        #
        # ⛔⛔ AND THE FIRST REPAIR BROKE PAIRING ITSELF. It excluded any message
        # containing "use", which is the word in "use this code K7XQ-9B2M" — the
        # commonest way anybody types one — so the client answered by asking for
        # the code that was already in the sentence. Cross-verify caught it; the
        # SAYING-A-CODE words have to win over the naming-a-machine words, because
        # a message that says "code" is about a code whatever else it says.
        # ⛔ `link` WAS IN THE ACT-VERB LIST AND IN NO OTHER, so `link my computer`
        # reached the catch-all — which also meant its negation veto could never
        # fire, because there was nothing to veto.
        _pairing = re.search(r"\b(pair|pairing|code|codes|connect|add|link)\b", low)
        # ⛔⛔ TWO WAYS TO PAIR A COMPUTER NOBODY ASKED TO PAIR, both measured:
        #   `hide device LABPC001`            PAIRED it
        #   `status of support code AB12CD34` PAIRED it
        # This verb list was hand-written and named NO visibility verb and NO read
        # verb, so a hide or a status question carrying an id fell straight through
        # to the pairing return. ⭐ It is DERIVED from the setter inventory now —
        # the standing rule, and the same fix as the conjunction signal: the words
        # a branch must know about are the words the file already lists.
        # ⛔⛤ AND IT WENT SHORT AGAIN — WAVE 1.2 MEASURED THREE MORE. The RUN and
        # CONSENT verbs were missing, so a code-shaped token in a sentence about
        # an existing machine PAIRED it:
        #   `stop the machine LABPC001 run`      PAIRED LABPC001
        #   `approve the machine LABPC001`       PAIRED LABPC001
        #   `did my logs go through? code AB12CD34`  PAIRED THE SUPPORT CODE
        # The last one is the worst: a support code is taught at two places in
        # SKILL.md and is not an access code at all. Derived where a list exists.
        _existing = re.search(rf"\b(?:switch to|run (?:it |everything )?on|use|using|"
                              rf"select|{_UNLINK_VERBS[3:-1]}|ask|asking|"
                              rf"request|requesting|borrow"
                              rf"|{_VIS_SETTERS[3:-1]}"
                              rf"|{_VIS_HIDE_ALL[3:-1]}|{_VIS_PUBLISH_ALL[3:-1]}"
                              rf"|stop|end|abort|cancel|pause|resume|unpause|retry|skip"
                              rf"|approve|accept|allow|grant|deny|refuse|reject|block"
                              rf"|logs?|log\s+files?|diagnostics|support"
                              rf"|status|state|check|show|list|progress|which|what)\b", low)
        # ⛔ A READ VERB BEATS THE CODE WORD. The comment above says a message that
        # says "code" is about a code whatever else it says — true for `use this
        # code`, false for `status of support code AB12CD34`, which is a QUESTION
        # about one and was answered by pairing it.
        _reading = re.search(r"^(?:\W*)(?:status|state|check|show|list|progress|"
                             r"what|which|who|where|why|how|is|are|did|does|has|have)\b", low)
        # ⛔⛔ THE READ GUARD APPLIES TO `_pairing` ALONE, AND MY FIRST ATTEMPT AT
        # THIS BROKE PAIRING THE SAME WAY THE COMMENT ABOVE SAYS IT WAS BROKEN
        # BEFORE. I gated the whole condition on `_existing`, and `use` is in that
        # list and in `use this code K7XQ-9B2M` — the commonest way anybody types
        # one — so the client answered a pasted code with the catch-all. The
        # SAYING-A-CODE words still win; only a message that OPENS with a read verb
        # is a question about a code rather than a pairing.
        if _bare or (_pairing and not _reading) or (_kw and not _existing):
            return ["device-add", tok], None
    # ⛔ A PUBLISH REQUEST IS NOT A PAIRING REQUEST. "add my computer to the
    # public list" was answered with "paste the access code" — this rule sits
    # above everything and its verb list contains `add`.
    if re.search(r"\bpublic|\bfindable|\bdiscoverable\b", low):
        pass
    # ⛔⛔ AND NEVER AHEAD OF A RESEARCH REQUEST. This guard sits ABOVE rule 2b,
    # and widening its nouns made it swallow "research how to connect my mac" —
    # answering a research topic with "paste the access code". Rule 2b's own test
    # is the one that decides, so it is asked here first.
    elif (not _NL_RESEARCH_RE.match(t)) and (
            # ⛔⛤ `link` ONLY AS A VERB. Added to the pairing words in the same
            # wave that added the artefact-LINK surface, it answered
            # `the brief link for my mac` with pairing instructions — 8 driven
            # shapes. A verb opens the sentence; a noun has an article in front.
            (re.search(rf"\b(add|pair|connect)\b.*\b({_MACHINE_NOUNS_SAID})\b", low)
             or re.match(rf"{_NL_LEAD_IN}link\b.*\b({_MACHINE_NOUNS_SAID})\b", low))
            or re.search(r"\bpair (my|a|the|this)\b", low)):
        # ⛔⛔ THIS WAS THE ELEVENTH DEVICELESS SENTENCE, and it survived the wave
        # that abolished the other ten: one way out (paste a code), no word on
        # whether the account HAS a computer, no public list, no walkthrough. The
        # cull matched the old copies by wording, and this wording was not on the
        # list; the renderer-call guard counts CALLS, and this door made none.
        # ⭐ NOT A NEW SCREEN. `devices` renders the empty state on an empty
        # account and the code route on a populated one — the same move rule 6b
        # already made for "I don't have a computer".
        # ⛔ A MESSAGE CARRYING A CODE NEVER REACHES HERE: rule 1 returned
        # ["device-add", tok] above, before the `public` guard and this branch.
        return ["devices"], None

    # 1b. ⛔⛤ "help" AND "what can you do?" REACHED THE CATCH-ALL, whose line opens
    #     "I didn't catch a Super Research request in that." The list that follows
    #     is exactly the right answer — so the client knew what to say and told
    #     the person they had failed to say it. SKILL.md teaches both phrasings.
    if re.fullmatch(r"(?:please\s+)?(?:help|help me|what can you do|what do you do|"
                    r"what can i (?:do|say|ask)|what is super ?research|"
                    r"what'?s super ?research|how do i (?:start|begin|use this)|"
                    r"how does this work|getting started|commands?|options?)",
                    low):
        # ⛔⛤ AND THE ANSWER IS THE CAPABILITY LINE, NOT AN ACCOUNT CHECK. I
        # routed these to `status-account`, which prints `✓ Signed in as <email>`
        # and nothing else (since 2026-09-25 on every account) — so `help` answered
        # a question nobody asked. The list the comment calls the right answer is
        # the catch-all's own sentence, minus the line that blames the person.
        return None, [_NL_CATCH_ALL.split("that. ", 1)[-1]
                      if "that. " in _NL_CATCH_ALL else _NL_CATCH_ALL]

    # 2. Sign-in / connection questions — always a FRESH account check.
    # ⭐⭐ AND THE BARE ONES (owner, 2026-09-25). Driven through this resolver:
    # "Logged in?", "Signed in?" and "are you logged in?" reached the catch-all,
    # and "did the login work?" / "login status" STARTED A NEW SIGN-IN (rule 5's
    # `\blogin\b`) — which also makes the bridge throw away the parked sign-in
    # note. They are asked HERE, above every rule that can start a sign-in. A bare
    # "signed in" with no question mark stays where it was: after a sign-in link
    # it is a person saying they did it, not asking.
    _signin_q = _NL_SIGNIN_QUESTION.fullmatch(low)
    if re.search(r"\b(am i|are (?:we|you)|is (it|this|the agent|super ?research))\b.*\b(signed?[ -]?in|logg?ed[ -]?in|connected|authenticated)\b", low) or \
            re.search(r"\b(which|what) account\b", low) or "account status" in low or \
            "connection status" in low or \
            (_signin_q and (_signin_q.group("ask") or _signin_q.group("tail") == "yet"
                            or t.rstrip().endswith("?"))) or \
            _NL_LOGIN_CHECK.fullmatch(low):
        return ["status-account"], None

    # 2b. A message that STARTS with a research verb is a research request —
    #     resolved before every remaining rule so control/status/phase words in
    #     the TOPIC ("research how to stop smoking", "research the history of
    #     the podcast industry") can't hijack it. A trailing "without/no video|
    #     email" clause maps to the run flags; a bare "research status" tail
    #     falls through (that's a progress ask, not a topic).
    rm = _NL_RESEARCH_RE.match(t)
    if rm:
        topic = re.sub(r"[?.!]+$", "", rm.group(1)).strip().strip("\"“”'‘’")
        # ⛔⛔ THE RESEARCH BRANCH TOOK 100% OF RESEARCH-VERB OPENINGS — 392 of 392
        # driven — and `research my devices` STARTED A PAID RUN titled “my
        # devices”. The veto was a fullmatch on three bare words, so anything
        # longer was a topic by default.
        # ⛔ THE COST IS STATED, NOT DISCOVERED: `look into the Mars run` now
        # reaches the CATCH-ALL rather than status, because no later branch
        # claims that shape. A refusal costs nothing; the paid run it replaces
        # costs money, so this is the trade and it is deliberate.
        _not_a_topic = (
            re.fullmatch(r"(?:the |my )?(?:status|progress|updates?)", topic, re.I)
            # an inventory of this account's own machines is not a subject
            # ⛔⛤ THE DETERMINER IS REQUIRED AND IT IS POSSESSIVE. Optional, it
            # made a bare plural product noun "an inventory of this account's
            # machines": 90 of 96 driven `research phones|laptops|macs` reached
            # the catch-all, and those are ordinary subjects.
            or re.fullmatch(r"(?:my|our|this|these)\s+(?:own\s+)?"
                            rf"(?:{_MACHINE_NOUNS_SAID})", topic, re.I)
            # ⛔ A RUN'S OWN status or artefact is not a subject — and the test is
            # WHOSE, not which noun. Written as "status|progress|podcast… and
            # anything after it", this refused `research the status of the EV
            # market`, a perfectly good topic, and an existing test caught it
            # within the hour. What makes `research the status of my run` not a
            # topic is that the thing it asks about is THIS ACCOUNT'S.
            or re.fullmatch(rf"(?:{_NAME_DETERMINER}\s+)?"
                            rf"(?:status|progress|podcast|audio|video|brief|report|"
                            rf"links?|results?|logs?)\s+(?:of|from|for|on)\s+"
                            # ⛔ `the` GOES: the comment beside this says the
                            # test is WHOSE, and `the laptop market` is nobody's.
                            rf"(?:my|this|that)\s+"
                            rf"(?:run|research|{_MACHINE_NOUNS_SAID})\b.{{0,20}}",
                            topic, re.I)
            # ⛔⛤ AND THE `<word> run` VETO IS GONE. I shipped it with its cost
            # stated — `research the marathon run` — and cross-verify measured
            # the class as 22 driven idioms wide: a bank run, a print run, a
            # trial run, a fun run, the long run, a dry run. One measured case
            # (`look into the Mars run`) does not buy that. It reverts to a paid
            # run, which is the pre-existing behaviour, and it is recorded as an
            # open defect rather than paid for with twenty-two real subjects.
            )
        if topic and not _not_a_topic:
            flags: list[str] = []
            ex = re.search(
                r"[,;\s]*\b(?:without|minus|skip(?:ping)?|drop(?:ping)?|leave out|no)\s+"
                # ⛔⛤ DERIVED. Hand-written, this was short by audio, youtube,
                # openai and anthropic against the very lists the loop five
                # lines below iterates — so `research tesla without audio`
                # started a PAID RUN titled “tesla without audio” with the
                # exclusion silently dropped.
                rf"(?:the\s+|a\s+|any\s+)?(?:{'|'.join(_NL_PHASE_WORDS)}|"
                rf"{'|'.join(_NL_AGENT_WORDS)})s?\b",
                topic, re.I)
            if ex:
                clause = topic[ex.start():].lower()
                topic = topic[:ex.start()].rstrip(" ,;.")
                hard = []
                for p in _NL_PHASE_WORDS:
                    if p not in clause:
                        continue
                    if p == "video":
                        flags.append("--no-video")
                    elif p == "email":
                        flags.append("--no-email")
                    else:
                        hard.append("the " + p)
                # P2 agents have no research-time flag either — same honest
                # two-step (skip them right after the run starts).
                for a in _NL_AGENT_WORDS:
                    if a in clause:
                        disp = _AGENT_DISPLAY.get(_SKIP_AGENTS.get(a, a), a)
                        if disp not in hard:
                            hard.append(disp)
                if hard and topic:
                    # No research-time flag exists for these — offer the
                    # honest two-step instead of silently ignoring the ask.
                    return None, [
                        f"I can start “{topic}” right away — {', '.join(hard)} "
                        "can be trimmed once the run starts (just ask me to skip "
                        "it then). Say yes to start."]
            if topic:
                return ["research", topic] + flags, None
            return None, ["Happy to fire a Super Research — what topic?"]
        if not topic:
            return None, ["Happy to fire a Super Research — what topic?"]

    # 2b-i. ⛔⛔ TWO COMMANDS IN ONE MESSAGE GO TO THE CATCH-ALL, NEVER HALFWAY.
    #     `pause the run and switch to the office PC` paused a run called “run and
    #     switch to the office PC” and dropped the switch; `stop the tesla run and
    #     hide my mac` offered to stop a run called “tesla run and hide my mac”.
    #     Both did something, to a name the person never said, and said nothing
    #     about the half they lost.
    # ⛔⛔ IT IS A RETURN, NOT A BAIL, and that is the whole lesson of wave 1.1: a
    #     veto in an ordered ladder hands its message to the NEXT branch, which
    #     then acts on the wrong feature. Four defects in one wave came from that.
    # ⛔ AND IT SITS BELOW THE RESEARCH BRANCH ON PURPOSE. A TOPIC is allowed to
    #     contain anything — `research how to stop smoking and start running` is
    #     one ask, and a compound test above the research rule would refuse it.
    if _is_compound_ask(t):
        return None, [_NL_CATCH_ALL]

    # 2c. Sending logs to support. AFTER the research rule on purpose — "research
    #     how log shipping works" is a topic, not a request to send anything —
    #     and it needs BOTH a giving verb and the word logs, so "check the logs"
    #     and "what do the logs say" fall through to the status rules where they
    #     belong. The bare command only SHOWS what would go, so resolving this
    #     eagerly cannot send anything by mistake.
    if re.search(r"\b(logs?|log ?files?|diagnostics?)\b", low) and re.search(
            r"\b(send|share|upload|submit|report|give|email|hand)\b", low):
        argv = ["send-logs"]
        # ⛔⛔ ONLY AN EXPLICIT ASK FOR THE COMPUTER'S OWN LOGS REACHES THE FLAG,
        # and "everything" / "all of them" deliberately do NOT. That material is
        # every run the machine has ever done for everyone who uses it, and a
        # person saying "send all the logs" means all of THEIRS — reading it the
        # other way turns a broad word into a request they did not make. The
        # narrow phrasing is reachable because the no-runs branch offers it in
        # those words, so the one case that genuinely needs it has a route.
        if re.search(r"\b(computer|machine|device)(?:’s|'s)?\s+own\b", low) or \
                re.search(r"\bown\s+(logs?|log ?files?|diagnostics?)\b", low):
            argv.append("--machine")
        # ⛔ THE AGENT'S OWN LOG NEEDS ITS OWN WORDS, and they must not overlap with
        # the ones above. "the computer's own logs" and "the agent's log" are two
        # different machines, so a pattern loose enough to catch both would send
        # material nobody asked for — the same reasoning that keeps "everything"
        # away from --machine.
        if re.search(r"\b(agent|bridge)(?:’s|'s)?\s+(own\s+)?(log|logs)\b", low) or \
                re.search(r"\bagent\s+log\b", low):
            argv.append("--agent-log")
        return argv, None

    # 2d. PUBLIC COMPUTERS — browse, ask, what you are waiting on, and the two
    #     things this surface cannot do.
    #
    # ⛔⛔ ABOVE RULE 3 AND ABOVE RULE 4, AND BOTH PLACEMENTS ARE LOAD-BEARING.
    # Measured against this resolver before the rules were written:
    #   · "cancel my access request"            → rule 3 → “Stop “access request”?
    #     It ends the run” — a run-stop confirm quoting the person's own words
    #     back as a research title.
    #   · "remove my request for the Studio PC" → rule 4 → “Unlink “request for
    #     the Studio PC”?” — a DESTRUCTIVE confirm, because "PC" satisfies its
    #     device noun; say yes and it dead-ends on a device that never existed.
    #   · "show me public devices", "which devices can I ask for" → rule 4 → the
    #     account's OWN machines: a complete-looking answer to another question.
    #
    # ⛔⛔ AND SITTING ABOVE THEM IS WHY THE FIRST DRAFT WAS WRONG SIX WAYS. A rule
    # this early sees every message, so each clause needs its own subject or it
    # steals one. Cross-verify found all six after the wave was green:
    #   · a bare "waiting for …" answered EVERY run-progress question with
    #     "You're not waiting on any computer";
    #   · the browse clause had no verb gate, so "make my computer public",
    #     "is my computer public?", "stop the run on the shared machine" and
    #     "ask for the podcast on my computer" all listed strangers' machines;
    #   · "ask for <any six-letter word>" reached the disclosing consent, because
    #     the is-this-an-id test was a bare length check;
    #   · "ask for access to the studio pc" made the machine's name
    #     "access to the studio pc", which nothing can ever resolve;
    #   · the withdraw clause had no machine context and ate "cancel the video";
    #   · an OWNER asking who is queued for their machine was told nobody is.
    #
    # ⛔ AND IT EMITS NO FLAGS. A routable flag has to be listed in `_DO_FLAGS`
    # and has to be store_true, so the object of every verb here is a POSITIONAL
    # — the same reason `--runs` is argument-only.
    # ⛔⛔⛔ POLARITY IS COMPUTED, NOT COLLECTED. `_hiding_kw` below was a
    # polarity-FREE bag of words with a negation arm bolted on as one more `or` —
    # so a negator could only ever ADD "hide" and never cancel one, and three
    # phrasings executed the exact opposite of what was asked:
    #   `make my mac not private`        EXECUTED private (and named it "mac not")
    #   `turn on sharing for my mac`     EXECUTED private — turning sharing ON hid it
    #   `un-hide the Studio PC`          EXECUTED private
    #   `make my Now or Never Mac public` EXECUTED private — the word `never` INSIDE
    #                                    the machine's own NAME flipped the request
    # ⭐ THE NEGATED POLARITY PHRASE IS SUBTRACTED FIRST, then re-added on the
    # OTHER side. That is what makes `not private` a PUBLISH instead of a hide: the
    # words are removed from the bag before either arm reads it, so neither arm can
    # see the polarity the person negated.
    _pol_src = _NEG_IN_NAME.sub(r"\1", _outside_quoted_names(low))
    _neg_hide_side = re.search(
        rf"\b(?:not|no\s+longer|never)\s+(?:be\s+|being\s+|stay\s+|remain\s+)?"
        rf"{_HIDE_POLARITY}\b", _pol_src, re.I)
    _neg_public_side = _NEG_PUBLISH_SIDE.search(_pol_src)
    _pol_low = _NEG_BEFORE_POLARITY.sub(" ", _pol_src)
    _public_kw = (re.search(r"\bpublic(?:ly)?\b|\bsomebody else|\bsomeone else"
                            r"|\bother (?:people|persons?|users?)\b", _pol_low)
                  # `not private` is a request to PUBLISH.
                  or _neg_hide_side
                  # ⛔ `un-hide` IS THE OPPOSITE OF `hide`, and it executed a hide.
                  # Excluding it from the hide arm only got it as far as the
                  # catch-all; the request it makes is a publish.
                  # ⛔⛤ AND THIS LIST WENT SHORT TOO — four of the seven hide verbs
                  # were missing, so `un-disable`, `un-unpublish` and `un-unshare`
                  # answered with a DEVICE LIST while `un-hide` published. The
                  # hide guard opposite this already spells `(?<!un-)(?<!un )`;
                  # this arm has to spell the same two forms, and both are
                  # DERIVED from the hide verbs rather than typed a third time.
                  or re.search(rf"\bun[- ]?{_VIS_HIDE_ALL}\b|\bun-?conceal\b",
                               _pol_low))
    # ⛔⛔ ONE NOUN LIST, TWO QUESTIONS, AND THEY HAD DRIFTED. `_machine_kw` asks
    # whether a computer is being talked about; `_mine_kw` asks whether it is the
    # ASKER'S. They were written as two literals two lines apart and ended up
    # differing by two words — `macs?` and `nodes?` were in one and not the other
    # — so every guard built on `_mine_kw` silently failed for the commonest word
    # for a Mac. Measured 2026-09-07, four live defects, all of them mine from
    # 7.9-2 and every one of them a defect a comment here claimed was fixed:
    # "make my mac public" and "is my mac public" listed STRANGERS' machines,
    # "who is waiting on my mac" showed the asker's own outgoing list, and "stop
    # offering my mac" became a run-stop quoting the phrase as a research title.
    # One list now, so the next word added to it cannot land in only one place.
    _machine_kw = re.search(rf"\b({_MACHINE_NOUNS_SAID})\b", low)
    _ask_kw = re.search(r"\b(ask|asked|asking|request|requests|requested|apply|"
                        r"borrow)\b", low)
    # ⛔ THE FOUR SUBJECTS THAT ARE NOT THIS RULE'S. A message carrying one of
    # them belongs to a rule further down and must fall through untouched: an
    # artefact or a run, a run control, an unlink, or the person's OWN machine.
    # ⛔⛔ "RESEARCH COMPUTER" IS A MACHINE, NOT AN ARTEFACT — and it is the
    # DEFAULT LABEL of every machine nobody has renamed, printed verbatim by the
    # browse list and by this client's own picker ("Say for example: make
    # “Research computer” public."). With `research` in the artefact list, every
    # owner verb aimed at one fell to the catch-all, including the exact string
    # the client had just told the person to type. Blanked for this test only.
    # ⛔ THE DETERMINER SLOT WAS MISSING, so `research my computers` still carried
    # the artefact word `research` and failed the device-list gate — it reached
    # the catch-all while `research my devices` answered. Two spellings of the
    # same ask, two answers.
    _low_no_rc = re.sub(rf"\bresearch(?:es)?\s+(?:{_NAME_DETERMINER}\s+)?"
                        rf"(?:own\s+)?(?:{_MACHINE_NOUNS_SAID})\b", "  ", low)
    _artefact_kw = re.search(r"\b(podcasts?|audio|videos?|reports?|briefs?|links?|"
                             r"status|progress|updates?|research(?:es)?|topics?|"
                             r"logs?|results?|runs?|emails?)\b", _low_no_rc)
    # ⛔ `cancel` WAS IN THE RUN-CONTROL VERB LIST AND NOT IN THIS ONE, and the two
    # lists differed by exactly that word — so `cancel on my Studio PC` reached
    # the device list while the identical `stop on my Studio PC` reached the
    # catch-all. Same question, two answers.
    # ⛔⛔ AND `drop` STAYS IN IT, THOUGH IT ONCE VETOED THE BRANCH IT ALSO
    # BELONGS TO. `drop my Studio PC` failed the visibility gate here and reached
    # the CATCH-ALL, so I first wrote a machine-noun exclusion — and the mutation
    # harness then showed that exclusion measures NOTHING: `drop` is in the
    # device verbs and in the unlink verbs now, so every `drop <machine>` phrasing
    # reaches the unlink confirm by that road whether this vetoes or not. A guard
    # that cannot change an outcome is not a guard; the simpler list is the true
    # one. ⭐ This is the harness refuting my own reasoning, which is what it is for.
    _control_kw = re.search(r"\b(stop|end|abort|pause|resume|unpause|retry|skip|"
                            r"cancel|drop)\b", low)
    _unlink_kw = re.search(r"\b(unlink|forget)\b", low)
    # ⛔ A THREE-WORD MACHINE NAME DEFEATED THE TWO-WORD GAP, so
    # `advertise my Now or Never Mac publicly` was routed as somebody ELSE's
    # machine and answered with the browse list of strangers' computers.
    # ⛔⛤ AND A POLARITY WORD IN THE GAP DOES NOT MAKE A MACHINE MINE. Widening
    # the gap to four turned `show me this week's public computers` and
    # `this is a public computer` into MY machine, which vetoed the browse
    # surface and sent them to a publish confirm naming “week's”.
    _mine_kw = re.search(rf"\b(my|mine|our|this)\b"
                         rf"(?:\s+(?!(?:{_POLARITY_WORDS[3:-1]})\b)[\w'-]+){{0,4}}\s+"
                         rf"(?:{_MACHINE_NOUNS_SAID})\b", low)
    # ⛔ MOVED UP FROM THE WAITING CLAUSE IN 7.9-3, unchanged. Two clauses above
    # it now need the same subject test, and a second copy of this pattern is
    # exactly the drift the noun list above records.
    _request_kw = re.search(r"\b(requests?|asks?|access|approvals?|permissions?)\b",
                            low)

    # ⛔⛔ OFFERING YOUR OWN MACHINE IS AN OWNER VERB AND IT IS NOT HERE YET.
    # Without this the browse clause answered "make my computer public" and
    # "is my computer public?" with a list of OTHER people's machines — a list
    # that structurally cannot contain the asker's own, since the projection
    # drops it.
    # ⛔ "stop sharing my machine" HAS NO PUBLIC WORD IN IT and rule 3 was eating
    # it as a run-stop, quoting "sharing my machine" back as a research title. It
    # is the same owner question in different words, so it belongs here.
    # ⛔⛤ THE FINITE PUBLISH VERBS LIVE HERE NOW, AND NOT IN A NARROWED THIEF.
    # `publish|offer|share my Studio PC` answered with the DEVICE LIST — 312
    # measured shapes — because this signal held only the gerunds while the verbs
    # themselves sat in the setter list, which admits nothing. The fix is to
    # WIDEN the signal, never to narrow the branch that was stealing them:
    # measured, that branch's veto hands the message to the CATCH-ALL, not to
    # this one. A veto in an ordered ladder is not inert — wave 1.1, four times.
    # ⛔ AND THE PUBLISH-SIDE POLARITY WORDS ARE PART OF THE SIGNAL, DERIVED. Four
    # of them — `visible`, `shared`, `listed`, plus `invisible` on the hide side —
    # sat in the polarity constant and in NO signal at all, so `make my mac
    # visible` answered with a device LIST while `make my mac not visible` hid it.
    # ⛔⛔⛔ THE SINGLE COSTLIEST WIDENING IN THIS WAVE, AND CROSS-VERIFY MEASURED
    # IT: admitting the bare publish-side polarity words moved 192 driven DEVICE
    # LIST requests onto a publish CONFIRM — `show my shared computers`,
    # `list my visible machines`, `who has access to my shared mac` — and every
    # copula STATEMENT with them: `my mac is listed as offline`,
    # `my laptop is shared with three people`, and worst,
    # `my mac is not visible on the network`, which is the exact opposite of the
    # sentence. The hide side three lines below has carried `(?<!\bis )` for a
    # wave; the publish side got the same words with no guard at all.
    # ⭐ THE FIX IS THE VERB. `public`/`publicly` stay bare — they are `_public_kw`
    # and they are what people say — but `shared|sharing|visible|listed` mean a
    # REQUEST only when a setter is asking for one. Driven: every phrasing the
    # document teaches goes through a setter, so nothing taught breaks.
    _offering_kw = (re.search(rf"\b{_VIS_PUBLISH_ALL}\b", low)
                    or (re.search(rf"\b{_alt(_PUBLISH_POLARITY_WORDS)}\b", low)
                        and re.search(rf"\b{_VIS_SETTERS}\b", low)
                        and not re.search(rf"\b(?:is|are|was|were|isn'?t|aren'?t|"
                                          rf"wasn'?t|weren'?t)\s+(?:not\s+)?"
                                          rf"(?:\w+\s+){{0,2}}"
                                          rf"{_alt(_PUBLISH_POLARITY_WORDS)}\b", low))
                    # ⛔ `let people find my mac` IS THE PHRASING SKILL.md TEACHES
                    # and it answered with a device list. The hide side already
                    # knows the shape — `stop LETTING people FIND it` is one of
                    # its arms — and the publish side, which is the one the
                    # document puts in a person's mouth, did not.
                    # ⛔⛤ THE AUDIENCE IS GENERIC AND THE VERB IS `find`, BOTH
                    # NARROWED AFTER AN EXISTING TEST CAUGHT ME. Written as a
                    # wildcard gap plus `find|use|…`, this stole
                    # `let them use my computer` — which is a CONSENT decision
                    # about a person already waiting, not a publish. `them` names
                    # somebody; `people` names nobody. And `use` belongs to that
                    # branch and to the ask branch; publishing is about being
                    # FOUND.
                    or re.search(r"\blet\s+(?:people|persons|users|anyone|anybody|"
                                 r"everyone|everybody|others|strangers|folks|"
                                 r"other\s+(?:people|persons?|users?))\s+"
                                 r"(?:find|see|discover|locate)\b", low))
    # ⛔⛔ THE WORDS FOR HIDING CARRY NO "PUBLIC" IN THEM. "hide my computer",
    # "unlist my mac", "make my pc private", "stop offering my machine" — every
    # one of those fell through to the catch-all or, worse, to rule 3, which
    # quoted "offering my mac" back as a research title and offered to stop it.
    # ⛔⛔ HIDING IS OFTEN SAID WITHOUT THE WORD "PRIVATE" — cross-verify found
    # eight shapes that carry no hiding word at all and every one of them
    # reached the PUBLISH confirm, i.e. the exact opposite of what was asked.
    # "turn off sharing", "disable sharing", "no longer share it", "remove it
    # from the public list", "undo making it public", "it should not be public".
    _hiding_kw = (
        # ⛔ `un-hide` CONTAINS `hide` BECAUSE A HYPHEN IS A WORD BOUNDARY, and it
        # executed a hide. Same for `un-delist` and `un-unlist`.
        # ⛔⛔⛔ AND THE GUARD COVERED ONLY THIS ARM. `disable|unshare|deregister|
        # delist` sat in a SECOND arm below with no lookbehind, so
        # `un-delist my Studio PC` HID the machine — the person asked to un-hide
        # and got a hide, while `un-unlist` correctly published. Two arms, two
        # answers to the same question, which is what made it a bug and not a
        # design. The arms are now ONE, the verbs are DERIVED, and the guard
        # cannot be given to half of them again.
        re.search(rf"(?<!un-)(?<!un )\b(?:{_HIDE_POLARITY[3:-1]}|hidden|unlisted|"
                  rf"{_VIS_HIDE_ALL[3:-1]})\b", _pol_low)
        # ⛔⛔ THE TWO HALVES OF THIS ARM NEEDED DIFFERENT VERBS, AND SHARING ONE
        # LIST MADE `turn on sharing for my mac` HIDE IT. `off` belongs with the
        # neutral verbs (turn/switch/shut); the -ING words only ever mean a hide
        # after a verb that is itself negative — `stop sharing`, `shut down
        # listing` — never after `turn`, which takes a direction and in
        # `turn ON sharing` takes the opposite one.
        or re.search(r"\b(?:turn|switch|shut|toggle)\b(?:(?!\bon\b)[^.?!]){0,20}"
                     r"\b(?:off|down)\b", _pol_low)
        or re.search(r"\b(?:stop|shut|quit|cease|end|no longer)\b[^.?!]{0,20}"
                     r"\b(?:offering|sharing|listing|publishing|letting|showing|"
                     r"allowing)\b", _pol_low)
        or re.search(r"\b(take|remove|drop|pull)\b.{0,30}"
                     r"\b(off|out of|from)\b.{0,24}\b(list|public|"
                     r"directory)\b", _pol_low)
        or re.search(r"\bundo\b.{0,24}\bpublic\b", _pol_low)
        # ⛔⛔ A NEGATION IN FRONT OF "PUBLIC" IS A HIDE — BUT ONLY IMMEDIATELY IN
        # FRONT OF IT. The 40-character span this replaces is what let `never`
        # inside a machine NAME reach `public` and hide the machine.
        or _neg_public_side)
    # ⛔⛔ A POLITE IMPERATIVE IS NOT A QUESTION. "can you make my mac public"
    # and "could you hide my mac" are the commonest way anybody asks for either
    # verb, and reading them as state questions answered neither. The
    # discriminator is whether a SETTER follows the politeness, not the opening
    # word — "is my mac public" has no setter and stays a question.
    # ⛔⛔ IT NEEDS THE LEAD-IN TOO, AND I BROKE THIS BY GIVING IT TO ONLY ONE SIDE.
    # `_asking_state` below is `question-word AND NOT this`. I let a lead-in
    # precede the question word and left this one anchored at bare `^`, so
    # `hey can you hide my computer` and `so could you make my computer public`
    # made the question test fire while its own veto silently could not — and
    # both were answered with a bare device list instead of doing the thing.
    # Measured against the revision this wave started from: eleven phrasings.
    # ⛔ DERIVED — the fourth hand copy of the setter list, also twelve of
    # twenty-one, so `can you delist my Studio PC` and `could you take my mac off
    # the list` were read as QUESTIONS and answered with a device list.
    _polite_imperative = re.match(_NL_LEAD_IN + r"(?:can|could|would|will|please|do)"
                                  r"\s+(?:you\s+)?"
                                  rf"(?:please\s+)?{_VIS_SETTERS}\b",
                                  low)
    # ⛔⛔ THE LEAD-IN IS WHY THIS WAS ANCHORED WRONG. `^` alone meant one
    # conversational word turned a read-only question into an offer to publish.
    _asking_state = (re.match(_NL_LEAD_IN + r"(is|are|does|do|can|could|who|what|"
                              r"which|how|tell me (?:if|whether)|check)\b", low)
                     and not _polite_imperative)
    # ⛔⛔ THE SUBJECT MUST BE ONE OF THIS ACCOUNT'S OWN MACHINES, AND A BARE
    # SETTER IS NOT THAT. Widening the gate to any setter verb let "switch to a
    # public computer", "put me on a public computer" and "make a list of public
    # computers" reach the publish confirm, each naming a fabricated machine
    # ("to a", "me", "list of"). ⛔ And "hide other people's computers from me"
    # — a BROWSE wish — silently made the asker's own machine private.
    # ⛔⛔ "OTHER PEOPLE'S", NOT "CONTAINS THE WORD PUBLIC". The first version of
    # this gate keyed on `_public_kw`, which matches the bare word — and bailed
    # on "make the Studio PC public", a regression this repair introduced and
    # this comment exists to stop being reintroduced. What marks a message as
    # about somebody ELSE'S machine is the phrase that says so.
    # ⛔ AND NOT WHEN THE ASKER NAMES THEIR OWN MACHINE IN THE SAME BREATH.
    # "offer my machine to other people" is the plainest way to say publish, and
    # a bare other-people test bailed on it — the second regression this one
    # gate produced while being narrowed.
    _about_others = (re.search(r"\bsomebody else|\bsomeone else|\bother (?:people|"
                               r"persons?|users?)\b|\bother people'?s\b", low)
                     and not _mine_kw and not re.search(r"\bmy own\b", low))
    _named_target = (re.search(rf"\b{_VIS_SETTERS}\s+"
                               rf"(?:the|my|our|this|that)\s+[\w' -]*"
                               rf"(?:{_MACHINE_NOUNS_SAID})\b", low)
                     # ⛔ A QUOTED NAME CARRIES NO ARTICLE, and the picker's own
                     # worked example quotes one: `make “Research computer”
                     # public`. Without this the string the client just told the
                     # person to type reached the browse list.
                     # ⛔⛤ AND A NAMED MACHINE IS A NAMED TARGET WHATEVER THE
                     # VERB, once a polarity word is in the message. `list the
                     # Studio PC publicly` answered with the BROWSE list of
                     # strangers' machines, because `list` is deliberately not a
                     # setter — it is the device-LIST request word — so no arm
                     # here saw the machine the person had named. Shape, not
                     # vocabulary: determiner, name, machine noun.
                     # ⛔ IT NEEDS A REAL NAME AND A SINGULAR NOUN, because
                     # written as "determiner, anything, machine noun" it claimed
                     # `list the public computers` and `find me a public
                     # computer` — BROWSE requests — from the branch that serves
                     # them. Two existing tests caught it. The adjective `public`
                     # is not a name, and a set of machines is not one machine.
                     or (re.search(rf"\b{_POLARITY_WORDS}\b", low)
                         and re.search(
                             rf"\b\w+\s+{_NAME_DETERMINER}\s+"
                             rf"(?:(?!(?:{_POLARITY_WORDS[3:-1]}|other|own|"
                             rf"more|any|some)\b)[\w'-]+\s+){{1,3}}"
                             rf"{_MACHINE_SINGULAR}\b", low))
                     # ⛔ DERIVED. Spelled out, this copy held twelve of the
                     # twenty-one setters — `take`, `remove`, `drop`, `pull`,
                     # `delist`, `unshare`, `deregister`, `advertise` and
                     # `expose` were all missing, so a quoted name after any of
                     # them was not a named target at all.
                     or re.search(rf"\b{_VIS_SETTERS}\s+"
                                  rf"[{re.escape(_NL_QUOTE_CHARS)}]", t))
    # ⛔⛔ A SET GETS IN, AND IT CAN ONLY EVER LEAVE BY THE REFUSAL. `make all the
    # computers public` answered with the BROWSE list of STRANGERS' machines and
    # `hide every computer` reached the catch-all, both because this gate needs
    # `my`/`our` or a determiner-led target and a set supplies neither. The arm
    # is paired with a SETTER VERB on purpose: without that, `find public
    # computers` — a browse — would enter and be refused, which is the mirror of
    # the defect being fixed. Entering on a set cannot act: the refusal below
    # sits ahead of both returns.
    # ⛔ A BARE MACHINE TOKEN IS A NAMED TARGET. Without this the visibility gate
    # had no way to see `hide LABPC001` as naming anything, so the largest single
    # class of dead phrasings in the wave stayed dead.
    # ⛔⛤ AND THE TOKEN MUST BE THE WHOLE OBJECT. Written as "a token anywhere
    # after a setter", it claimed ordinary sentences that merely contain a
    # hyphenated identifier: `share ISO-8601 with the team`, `publish RFC-2119`,
    # `share COVID-19 findings`, and `take GPT-4 off the list` EXECUTED a hide.
    _id_target = bool(re.fullmatch(rf"(?:{_NL_LEAD_IN})?{_VIS_SETTERS}\s+"
                                   rf"(?:{_NAME_DETERMINER}\s+)?"
                                   rf"[A-Za-z0-9][A-Za-z0-9._-]*"
                                   rf"(?:\s+(?:to|into|on|onto|as)?\s*"
                                   rf"{_VIS_POLARITY_ALL})?"
                                   rf"(?:[\s,;]+(?:{_NAME_TAIL_ALWAYS[3:-1]}|"
                                   rf"{_NAME_TAIL_COMMA_ONLY[3:-1]}))*[.!?]*", low)
                      and re.search(rf"\b{_VIS_SETTERS}\s+(?:{_NAME_DETERMINER}\s+)?"
                                rf"([A-Za-z0-9][A-Za-z0-9._-]*)\b", t, re.I)
                      and _looks_like_a_machine_token(
                          re.search(rf"\b{_VIS_SETTERS}\s+(?:{_NAME_DETERMINER}\s+)?"
                                    rf"([A-Za-z0-9][A-Za-z0-9._-]*)\b",
                                    t, re.I).group(1)))
    _set_target = bool(_request_names_a_set(t)
                       and re.search(rf"\b{_VIS_SETTERS}\b", low))
    # ⛔⛤ A PRONOUN POINTS AT THE MACHINE ON SCREEN. `take it off the public list`
    # is a phrasing SKILL.md teaches and it reached the catch-all: the hide signal
    # fired and no clause said the message had a target at all. It lands on the
    # PICKER, which is the honest answer to "it" — never on a confident guess.
    # ⛔⛔ AND IT NEEDS A POLARITY WORD, because without one `turn it off` — the
    # commonest way anybody says STOP THE RUN — reached this branch and executed
    # an UNCONFIRMED HIDE. The phrasing this clause exists for is
    # `take it off the public list`, which says `public` out loud.
    _pronoun_target = bool(re.fullmatch(
        r"(?:please\s+|can you\s+|could you\s+)*"
        r"(?:take|put|make|set|switch|turn|keep)\s+"
        r"(?:it|this|that|mine)\s+[^.?!]{0,40}", low)
        and re.search(rf"\b(?:{_POLARITY_WORDS[3:-1]}|list|listing|directory)\b", low))
    if (_public_kw or _offering_kw or _hiding_kw) \
            and (_mine_kw or re.search(r"\bmy own\b", low) or _named_target
                 or _id_target or _pronoun_target
                 or _set_target) \
            and not _about_others \
            and not _artefact_kw and not _unlink_kw \
            and not (_control_kw and not _hiding_kw):
        if _asking_state:
            return ["devices"], None
        # ⛔ THE MACHINE IS A HINT, NEVER A NAME THIS RULE INVENTS. 7.9-2 shipped
        # a clause that captured "access to the studio pc" as a machine name and
        # then quoted it in a consent question, naming a computer that could not
        # exist. What is passed here is validated against the account's OWN list
        # by the command, and an unresolvable hint degrades to the picker rather
        # than to a confident wrong machine.
        # ⛔⛔ TWO SHAPES, BECAUSE A VERB-FIRST HIDE HAS NO TRAILING KEYWORD.
        # "hide the studio pc" matched nothing, so the name was dropped and the
        # picker hid whichever machine it liked — unconfirmed. And `on|off|to`
        # as terminators captured "off sharing" out of "turn off sharing".
        # ⛔⛔⛔ THE QUOTED SPAN IS PAIRED, AND THIS IS THE ONE DEFECT IN WAVE 1.2
        # THAT ACTED ON THE WRONG MACHINE. Spelling the delimiters as a CLASS
        # made every quote character a terminator, so an APOSTROPHE inside the
        # name ended the capture: `hide "Sam's MacBook Pro"` captured “Sam”,
        # which then SUBSTRING-MATCHED a different machine and hid it, with a ✓.
        # Measured on an account holding only “Donna Mac”: `hide "Don't Send PC"`
        # hid Donna Mac. The curly ’ behaves identically and is what macOS and
        # iOS autocorrect actually type — and `<First>'s MacBook Pro` is what a
        # Mac calls itself out of the box, so this is the DEFAULT name shape.
        # ⛔ `_NL_QUOTED_RE` above already pairs correctly; the divergence was
        # here alone. Pairing means: a span opened with " ends at ", one opened
        # with “ ends at ”, and everything between is CONTENT.
        _vis_obj = ""
        # ⛔ THE `off the list` ARM IS READ BEFORE THE POLARITY ARM. Read after
        # it, `take my Studio PC off the public list` matched `take … public` and
        # captured “Studio PC off” — the word that makes the phrase a HIDE went
        # into the name. It cannot steal `take X public`, which has no
        # off/out-of/from in it.
        _vm = (re.search(rf"\b{_VIS_SETTERS}\s+{_QUOTED_SPAN}", t, flags=re.I)
               or re.search(rf"\b{_alt(_VIS_OFF_VERBS)}\s+(.+?)\s+"
                            rf"(?:off|out of|from)\b", t, flags=re.I)
               # ⛔⛔ A LINKING PREPOSITION BELONGS TO THE POLARITY, NOT THE
               # NAME. Written without it, the lazy capture swallowed the
               # preposition: `set my Studio PC to private` captured
               # “Studio PC to”, `put my Studio PC on private` captured
               # “Studio PC on”, and each refused a machine the person had named
               # correctly. Only the bare-adjective form was ever clean.
               # ⛔ AND THE POLARITY WORDS ARE DERIVED. Spelled here by hand the
               # list went short by one — `visible` was in the polarity constant
               # and missing from this arm, which is half of why
               # `make my mac visible` answered with a device LIST.
               or re.search(rf"\b(?:{'|'.join(_VIS_POLAR_VERBS)}|"
                            rf"{_VIS_PUBLISH_ALL[3:-1]})\s+"
                            rf"(.+?)\s+(?:(?:to|into|on|onto|as)\s+)?(?:the\s+)?"
                            rf"(?:{_NEG_WORDS}\s+)?(?:be\s+|being\s+|stay\s+|"
                            rf"remain\s+)?{_VIS_POLARITY_ALL}\b", t, flags=re.I)
               # ⛔⛤ EVERY VERB THE SIGNAL ADMITS NOW HAS A CAPTURE ARM, AND BOTH
               # SIDES ARE DERIVED FROM THE SAME LISTS THE SIGNAL READS. Wave 1.2
               # measured SEVEN routes that reached the visibility branch with no
               # arm here at all — `disable`, `unshare`, `deregister`,
               # `stop <x>ing`, `undiscoverable`, `take X private`, and
               # `share X with other people` — so each one handed the command a
               # machine it had never been told and fell through to the picker.
               # A signal and a capture written from two lists WILL diverge; the
               # only question is which verbs fall in the gap.
               or re.search(rf"\b{_VIS_HIDE_ALL}\s+(.+?)$", t, flags=re.I)
               or re.search(rf"\b{_VIS_PUBLISH_ALL}\s+(.+?)$", t, flags=re.I)
               or re.search(r"\b(?:stop|shut|quit|cease|end)\s+"
                            r"(?:off\s+|down\s+)?(?:offering|sharing|listing|"
                            r"publishing|letting|showing|allowing)\s+(.+?)$",
                            t, flags=re.I)
               # ⛔ `let <who> find <machine>` — the phrasing SKILL.md teaches,
               # which has a signal now and needed a capture to match it.
               or re.search(r"\blet\s+(?:people|persons|users|anyone|anybody|"
                            r"everyone|everybody|others|strangers|folks|"
                            r"other\s+(?:people|persons?|users?))\s+"
                            r"(?:find|see|discover|locate)\s+(.+?)$",
                            t, flags=re.I)
               # ⛔ THE LAST ARM IS SHAPE, NOT VOCABULARY, and it is last for that
               # reason. Some phrasings reach this branch on a POLARITY word with
               # a verb no inventory holds — `list my Studio PC publicly` is the
               # measured one, and `list` is deliberately not a setter because it
               # is the device-LIST request word. Between a verb and a polarity
               # word is a name whatever the verb was; every arm above gets first
               # refusal, so this can only catch what they left.
               # ⛔⛤ AND IT REFUSES A COPULA CLAUSE, because my first version did
               # not: `my mac is not public` is a STATEMENT, and this arm
               # captured “is not” as a machine name and offered to publish it.
               # A name never contains a copula.
               or re.search(rf"^\W*\w+(?:\s+\w+)?\s+"
                            rf"((?:(?!\b(?:is|are|was|were|isn'?t|aren'?t|has|"
                            rf"have|does|do|did)\b)[^.?!])+?)\s+"
                            rf"(?:{'|'.join(_NAME_END_ADVERB)}\s+)?"
                            rf"{_VIS_POLARITY_ALL}\b", t, flags=re.I))
        if _vm:
            # ⛔⛤ A QUOTED NAME IS TAKEN VERBATIM, AND THAT IS THE WHOLE ESCAPE
            # HATCH FOR EVERY TRIM IN THIS WAVE. The tail trim has to eat words
            # like `now` and `today` to fix the 592 phrasings a politeness word
            # broke — which means it can also eat a machine genuinely called
            # “Studio PC Now”. Quoting is what the picker already tells people to
            # do, so quoting is what must survive. My own test caught this: the
            # trim ran on the quoted capture too.
            _vis_quoted = bool(_vm.re.groups >= 3)
            _vis_obj = _cap(_vm).strip().strip(_NL_QUOTE_CHARS).strip()
            # ⛔⛔ THE FEATURE IS NOT THE MACHINE, AND MY OWN A/B CAUGHT THIS ONE
            # BEFORE IT SHIPPED. Giving every hide verb a bare `(.+?)$` arm made
            # `disable sharing on my mac` capture “sharing on my mac” as a
            # MACHINE NAME — a phrase that resolves to nothing, so a command that
            # used to reach the picker started refusing. `disable [sharing] on
            # [my mac]` names the setting first and the machine after the
            # preposition; the loop peels both, because people stack them
            # (`turn off sharing for my mac`).
            # ⛔ THE PREPOSITION IS REQUIRED, or the peel eats a NAME. Written as
            # a bare word list it turned `hide Sharing Mac` into “Mac”. A setting
            # word only means a setting when a machine follows it through `on`,
            # `for` or `of`; standing alone it is somebody's machine name.
            for _ in range(3):
                # ⛔ AND THE AUDIENCE IS NOT THE MACHINE EITHER. `stop letting
                # people find my pc` captured “people find my pc” — the people
                # are who, the pc is which. An existing test caught it.
                # ⛔ TWO PEELS, NOT ONE ALTERNATION. The audience phrase stands
                # on its own (`letting PEOPLE FIND my pc` — no preposition after
                # it), while a setting word only means a setting when a machine
                # follows it THROUGH one. Folding them into a single pattern made
                # the preposition mandatory for both and the audience survived.
                _peeled = re.sub(r"^(?:people|persons?|users?|anyone|anybody|"
                                 r"everyone|everybody|others|strangers|folks|"
                                 r"other\s+(?:people|persons?|users?))\s+"
                                 r"(?:to\s+)?(?:find|use|see|discover|access|"
                                 r"borrow|reach)\s+", "", _vis_obj,
                                 flags=re.I).strip()
                _peeled = re.sub(r"^(?:(?:sharing|listing|publishing|offering|"
                                 r"discovery|visibility|discoverability)\s+)?"
                                 r"(?:on|for|of|to|from|off|down)\s+", "",
                                 _peeled, flags=re.I).strip()
                if _peeled == _vis_obj or not _peeled:
                    break
                _vis_obj = _peeled
            # ⛔ AND THE DETERMINER STAYS ON A QUOTED NAME. Verbatim means
            # verbatim: a machine somebody called “my mac” is theirs to call that.
            if not _vis_quoted:
                _vis_obj = re.sub(rf"^{_NAME_DETERMINER}\s+", "", _vis_obj,
                                  flags=re.I).strip()
            _vis_obj = re.sub(r"[?.!,]+$", "", _vis_obj).strip()
            # ⛔ AN EXCLUSION CLAUSE IS NOT PART OF THE NAME. `hide the Studio PC
            # and leave all my other machines alone` captured the whole tail and
            # passed it as a machine name, which resolves to nothing and drops to
            # the picker — measured. The clause that says what to leave out is
            # the same one the set gate blanks, so it is trimmed from the same
            # constant rather than a second list that can drift.
            # ⛔⛔ AND IT MUST LEAVE SOMETHING BEHIND. Written to trim a trailing
            # clause, it ate the WHOLE capture when the name itself opens with a
            # trigger word — a machine called "Not My Mac" or "Other Than
            # Desktop" came back empty and the command fell to the picker, which
            # is the unconfirmed-wrong-machine outcome this branch exists to
            # avoid. Cross-verify measured seven of them against the revision
            # this wave started from.
            # ⛔⛤ THE QUOTED EXEMPTION LIVES IN THE TRIM ITSELF NOW — it takes
            # the whole message and bypasses when the capture IS the quoted span,
            # which is what made the hatch work at all six sites. Keeping a
            # second copy of the same condition here measured NOTHING: the
            # mutation harness proved the branch could not change an outcome.
            # ⭐ `_vis_quoted` still earns its keep below, where it exempts a
            # quoted name from the determiner strip and the bare-noun blank.
            _vis_obj = _trim_trailing_clause(_vis_obj, t)
            # ⛔ AND THE CATEGORY WORD IN FRONT COMES OFF, as it already does at
            # switch, remove and ask. Visibility was the one machine capture
            # without it, so `hide the machine LABPC001` looked up
            # “machine LABPC001” and found nothing — the 7.9-3 defect, still
            # live on hide and publish alone. The helper carries 1.1's guard
            # against eating a NAME whose own first word is a device noun.
            _vis_obj = _strip_leading_noun(_vis_obj)
            # A bare noun names no machine; neither does a phrase about other
            # people's, and quoting either back is the 7.9-2 defect shape.
            # ⛔ THE TEST IS ON THE CAPTURED OBJECT, NOT ON THE MESSAGE. The
            # first version also cleared the name whenever `_public_kw` matched
            # — which is every publish phrasing there is — so no machine could
            # ever be named. What disqualifies a capture is that IT names no
            # machine: a bare noun, a pronoun, or a phrase about other people's.
            # ⛔⛔ AND A SPAN THAT ENDS LIKE A CLAUSE NAMES NOTHING — see
            # `_names_a_machine`. Falling to the picker is the honest outcome;
            # hiding whatever “mac not” substring-matches is not.
            if _vis_obj and not _names_a_machine(_vis_obj):
                _vis_obj = ""
            # ⛔ AND A QUOTED NAME IS EXEMPT FROM THE BARE-NOUN BLANK TOO. The
            # escape hatch is that quoting means VERBATIM; a machine somebody
            # called “my mac” is theirs to call that.
            if not _vis_quoted and (re.fullmatch(
                    rf"(?:{_MACHINE_NOUNS_SAID}|it|them|one|ones|everything|"
                             rf"me|us|myself)", _vis_obj, flags=re.I)
                    or re.search(r"\bpublic|\bsomebody else|\bsomeone else|"
                                 r"\bother (?:people|persons?|users?)\b",
                                 _vis_obj, flags=re.I)):
                _vis_obj = ""
        # ⛔⛔ AND A SET IS NOT A TARGET. This branch is where 7.9-5's
        # `_asks_about_every_machine` lived as a `search` over the WHOLE message,
        # which refused `make “All Hands Mac” public` — the form the client's own
        # picker tells people to type — and refused every single-target request
        # that merely mentioned a set. It is asked here, about what THIS branch is
        # about to act on, with the capture allowed to win.
        # ⛔⛔ AND IT HAS TO BE HERE AND NOT ONLY IN THE HIDE ARM. Measured: `hide
        # my machines` and `hide my computers` RAN the unconfirmed hide with no
        # name at all, so the picker hid whichever machine it landed on; `make my
        # computers public` and `make my 3 pcs public` reached the publish
        # confirm quoting a name that cannot exist.
        if _request_names_a_set(t, _vis_obj):
            _verb = "hide" if _hiding_kw else "publish"
            return None, [f"I {_verb} one computer at a time. Ask me to list them "
                          f"and name the one to {_verb} — nothing changes until "
                          f"you do."]
        if _hiding_kw:
            # ⛔ NO CONFIRM ON HIDING. It takes a computer OFF a list; the only
            # thing it can cost is somebody not finding a machine they were
            # never promised. Confirming a strictly narrowing change teaches
            # people to click through the confirms that matter.
            return (["device-visibility", "private"] +
                    ([_vis_obj] if _vis_obj else []), None)
        return None, [_NL_CONFIRMS["device-visibility"].format(
            name=f"“{_vis_obj}”" if _vis_obj else "that computer")]

    # ⛔⛔ THERE IS NO WITHDRAW, SO SAY SO — but only about a REQUEST FOR A
    # MACHINE. Ungated, this clause answered "cancel the video" with a sentence
    # about owners and weeks. Nothing in the product cancels a filed request: the
    # app exposes exactly two operations on that collection, make one and list
    # them, and BOTH neighbouring rules answered this phrasing with a confident
    # wrong action.
    if _ask_kw and not _artefact_kw and \
            (_machine_kw or _public_kw or re.search(r"\baccess\b|\brequests?\b", low)) and \
            re.search(r"\b(cancel|withdraw|remove|delete|take back|undo|retract|"
                      r"forget)\b", low) and \
            re.search(r"\b(requests?|asks?|application)\b", low):
        return None, ["A request can’t be taken back once it’s made — it stays "
                      "with the owner until they answer it, or lapses on its own "
                      "after a week.",
                      "I can show you what you’re waiting on if that helps."]

    # ⛔⛔ ANSWERING SOMEBODY. Until 7.9-3 every phrasing below reached either
    # the catch-all, which denies having the verb, or — worse — the ASK consent
    # question: "approve the request for my Mac" offered to hand the owner's own
    # name to a stranger for a computer named "for my Mac". Measured live.
    _yes_kw = (re.search(r"\b(approve[sd]?|approving|accept(?:s|ed|ing)?|"
                         r"allow(?:s|ed|ing)?|grant(?:s|ed|ing)?|"
                         r"say(?:s|ing)? yes|said yes)\b", low)
               # ⛔ "give X access" is the plainest way an owner says yes and it
               # reached nothing. Bare `give` is far too broad, so the shape —
               # not the word — is what routes.
               or re.search(r"\bgives?\s+(?:\w+\s+){0,2}access\b", low)
               # ⛔⛔ "LET ME USE IT" IS THE REQUESTER'S SENTENCE, NOT AN OWNER
               # GRANTING. This shape was written for "let Sam use it" and
               # matched the commonest way anybody ASKS for a computer — and
               # sitting above the ask clause, it offered to approve a stranger
               # instead. "ask them to let me use their computer" is the
               # product's own advice wording and did the same.
               or re.search(r"\blet\s+(?!me\b|us\b|myself\b)"
                            r"(?:\w+\s+){0,2}(?:use|onto|on|in)\b", low))
    _no_kw = re.search(r"\b(deny|denies|denied|denying|reject(?:s|ed|ing)?|"
                       r"refus(?:e|es|ed|ing)|declin(?:e|es|ed|ing)|"
                       r"turn(?:s|ed)? (?:them |him |her |it )?down|"
                       r"say(?:s|ing)? no|said no)\b", low)
    # ⛔⛔ THE SUBJECT GATE IS THE WHOLE SAFETY OF THIS CLAUSE. `accept`, `allow`
    # and `grant` are ordinary English — "allow it to finish", "accept the risk"
    # — so on their own they must not route anywhere. The five words below mean
    # nothing else in this product: nothing here is approved, denied, rejected
    # or declined except a person waiting for a computer.
    _strong_decide = (re.search(r"\b(approve[sd]?|approving|deny|denies|denied|"
                                r"denying|reject(?:s|ed|ing)?|"
                                r"declin(?:e|es|ed|ing))\b", low)
                      # ⛔ TWO SHAPES, NOT TWO WORDS. Bare `say` and bare `let`
                      # are everywhere; "say yes to somebody" and "let somebody
                      # use it" are answers to a request and nothing else.
                      or re.search(r"\bsay(?:s|ing)? (?:yes|no) to\b", low)
                      or re.search(r"\bgives?\s+(?:\w+\s+){0,2}access\b", low)
                      or re.search(r"\blet\s+(?!me\b|us\b|myself\b)"
                                   r"(?:\w+\s+){0,2}(?:use|onto|on|in)\b", low))
    # ⛔⛔ A NEGATION IS NOT THE VERB IT CONTAINS. "don't allow anyone else to
    # use my computer" and "never allow strangers on my mac" returned an APPROVE
    # confirm — the exact opposite of what was asked, one "yes" from granting.
    # Neither is refused here either: what the person wants is a hide or a
    # sharer removal, and guessing between them is worse than the catch-all.
    # ⛔⛔ THE CURLY APOSTROPHE HERE TOO — see `_NEG_WORDS` for why the fix is a
    # character class and not a normalise of `t` (it feeds every name capture).
    # This is the copy that cost most, because this surface is DESTRUCTIVE:
    # `don’t approve sam` answered "Say yes to “sam”?", one reflexive yes from
    # letting a stranger onto the machine.
    _negated_decide = re.search(r"\b(don['’]?t|do not|never|no longer|not|cannot|"
                                r"can['’]?t|shouldn['’]?t|should not|won['’]?t|"
                                r"would not)"
                                r"\b[^.?!]{0,24}\b(allow|approve|accept|grant|"
                                r"let|say yes)\b", low)
    # ⛔⛔ MY OWN REQUEST IS THE ASKER'S STATUS QUESTION, NOT A DECISION. "has my
    # request been approved yet" and "why was my request denied" reached the
    # decide confirms, so somebody reading their own refusal was offered to
    # refuse a stranger — and a "yes" would have spent that stranger's week.
    _about_my_own_request = re.search(r"\bmy (?:access )?(?:requests?|asks?)\b", low)
    # ⛔ A QUESTION ABOUT ANSWERING IS NOT AN ANSWER. The visibility clause grew
    # this guard and the decide clause did not, so "how do I approve someone"
    # and "have I approved anyone" raised a confirm.
    _asking_about_deciding = re.match(r"^(how|why|what|when|who|which|should|"
                                      r"have|has|had|did|does|do|can|could|is|"
                                      r"are|was|were)\b", low)
    # ⛔⛝ THE WEAK VERBS NEED A SUBJECT THE STRONG ONES DO NOT. `accept`, `allow`
    # and `grant` are ordinary English, and the gate accepted a bare machine word
    # as their subject — so "allow it to finish on my computer" and "accept the
    # risk on my machine" raised a grant confirm. The comment above this clause
    # named those exact sentences as ones that must not route, and the gate did
    # not implement it. A weak verb now needs a REQUEST word or a person.
    _person_object = re.search(r"\b(person|people|somebody|someone|anyone|"
                               r"anybody|them|him|her|everyone)\b", low)
    _weak_ok = bool(_request_kw or _person_object)
    # ⛔ A BARE "I APPROVE" NAMES NOBODY AND NOTHING. On its own it granted the
    # single queued requester after one reflexive "yes"; a strong verb has to be
    # pointed at a request, a machine, a person, or an object of its own.
    _decide_subject = bool(
        _request_kw or _person_object or
        (_strong_decide and (_machine_kw or re.search(
            r"\b(?:approve|deny|reject|decline|accept|say (?:yes|no) to)\s+\S",
            low))))
    # ⛔ THE ASKER'S OWN STATUS QUESTION HAS AN ANSWER — their side of the queue
    # — so it is routed there rather than dropped on the catch-all, which would
    # deny having the verb somebody was plainly asking about.
    if (_yes_kw or _no_kw) and _about_my_own_request and not _artefact_kw:
        return ["device-requests"], None
    if (_yes_kw or _no_kw) and not _artefact_kw and not _control_kw \
            and not _negated_decide and not _asking_about_deciding \
            and (_strong_decide or _weak_ok) and _decide_subject:
        # ⛔ THE PERSON IS A HINT, VALIDATED LATER, NEVER INVENTED HERE. The
        # command matches it against the actual queue and falls back to printing
        # who IS waiting, so a bad capture costs a question rather than granting
        # a stranger a computer.
        _who = ""
        _wm = (re.search(r"\b(?:approve|grant|gives?|deny|refuse|decline)\s+"
                         r"(?:\w+\s+)?access\s+(?:to|for)\s+"
                         r"(.+?)(?:\s+\b(?:for|to|on|onto)\b|$)", t, flags=re.I)
               or re.search(r"\b(?:from|by)\s+(.+?)(?:\s+\b(?:for|to|on)\b|$)",
                            t, flags=re.I)
               or re.search(r"\b(?:say (?:yes|no) to|approve|approving|deny|"
                            r"denying|reject|decline|accept|allow|grant)\s+"
                            r"(.+?)(?:\s+\b(?:for|to|on|onto)\b|$)",
                            t, flags=re.I))
        if _wm:
            _who = re.sub(r"[?.!,]+$", "", _wm.group(1)).strip().strip(_NL_QUOTE_CHARS)
            # ⛔ THE SHARED DETERMINER LIST — this copy was missing `my` and
            # `our`, so `approve my colleague Sam` kept the possessive.
            _who = re.sub(rf"^{_NAME_DETERMINER}\s+", "",
                          _who, flags=re.I).strip()
            _who = re.sub(r"(?:'s|s')?\s*\b(requests?|asks?|application)\b\s*$",
                          "", _who, flags=re.I).strip()
            # ⛔ A PRONOUN, A POSSESSIVE OF MINE, OR A BARE MACHINE WORD IS NOT A
            # PERSON. "approve it", "let them use my computer", "approve the
            # request for my mac" all end up here with an object that names
            # nobody, and quoting one back is the defect 7.9-2 shipped.
            # ⛔ THE WORDS AROUND A PERSON ARE NOT THE PERSON. Cross-verify
            # found six captures quoted back as names that name nobody:
            # "access" ("grant access to sam"), "my" ("did the owner approve my
            # request"), "default" ("deny everyone by default"), "this", "here",
            # "marketing". A capture has to survive being stripped of the words
            # that surround an answer before it can be quoted as somebody.
            _who = re.sub(r"^(?:access|permission|entry|the request|request)\s+"
                          r"(?:to|for|from)?\s*", "", _who, flags=re.I).strip()
            # ⛔⛤ A PERSON'S NAME ENDS WHERE THE SENTENCE DOES. This site ran to
            # end-of-string, so `approve Sam please` asked "Say yes to
            # “Sam please”?" and `approve Sam and show me the rest` asked about
            # “Sam and show me the rest” — a CONSENT decision quoting a person
            # who does not exist. The same trim the other sites use.
            _who = _trim_trailing_clause(_who, t)
            # ⛔ AND THE CATEGORY WORD IN FRONT GOES, exactly as it does for a
            # machine. `approve the person Sam` asked "Say yes to “person Sam”?".
            # These are the words nobody is CALLED, so unlike the machine nouns
            # they need no identifier test behind them.
            _who = re.sub(r"^(?:person|user|account|colleague|coworker|co-worker|"
                          r"guy|woman|man|requester|requestor)\s+(?=\S)", "",
                          _who, flags=re.I).strip()
            _who = _strip_leading_noun(_who)
            if re.fullmatch(rf"(?:it|them|him|her|us|they|everyone|everybody|"
                            rf"persons?|people|somebody|someone|anyone|anybody|"
                            rf"this|that|here|there|now|yet|access|permission|"
                            rf"default|both|all|everything|one|ones|my|our|"
                            rf"my\s+\w+|our\s+\w+|{_MACHINE_NOUNS})", _who,
                            flags=re.I) or len(_who) > 60:
                _who = ""
        # ⛔⛔ THE MOST IMPORTANT CALL SITE IN THIS WAVE, AND THE SIGNED SIGNAL
        # COULD NOT SEE IT. There is no machine noun on this surface — the set is
        # of PEOPLE — so a plural-machine test missed the whole queue. And the
        # cost here is not a bad question: `let them all in`, `refuse everyone`
        # and `deny Both` capture NOTHING, `_who` is blanked, and
        # `_resolve_asker("")` RETURNS THE SOLE WAITING ROW — so one stranger is
        # let onto the machine, or one person refused for seven days, while the
        # person who typed it believes they answered the queue. Measured against
        # this resolver, post-revert.
        if _request_names_a_set(t, _who):
            _plural = "no to" if (_no_kw and not _yes_kw) else "yes to"
            return None, [f"I say {_plural} one person at a time. Ask me who is "
                          f"waiting and name them — nobody is answered until you "
                          f"do."]
        _named = f"“{_who}”" if _who else "that request"
        if _no_kw and not _yes_kw:
            # ⛔⛔ DENYING CONFIRMS TOO, AND THE WEB APP DOES NOT. Over there the
            # queue and the buttons are on one screen, so the cost is in front of
            # the person as they click; here there is no screen. And the cost is
            # real and invisible: a refusal stops that person asking again for a
            # week, the app tells THEM and tells the owner nothing at all.
            return None, [_NL_CONFIRMS["device-deny"].format(name=_named)]
        return None, [_NL_CONFIRMS["device-approve"].format(name=_named)]

    # ⛔⛔ AN OWNER ASKING WHO WANTS THEIR MACHINE IS NOW A REAL QUESTION WITH A
    # REAL ANSWER. Until 7.9-3 this named the web app, because the queue had no
    # verb behind it on this surface; `device-requests` carries both halves now.
    if _mine_kw and re.search(r"\b(who|whos|whose|anyone|anybody|somebody|someone|"
                              r"people|how many|show|list|see|any|what)\b", low) and \
            re.search(r"\b(wants?|wanting|asks?|asked|asking|requests?|requested|"
                      r"requesting|queued|queue|waiting|access)\b", low):
        return ["device-requests"], None

    # What am I waiting on? ⛔ IT NEEDS ITS OWN SUBJECT. A bare "waiting for …"
    # answered every run-progress question — "still waiting for the podcast",
    # "waiting for the report" — with "You're not waiting on any computer".
    # ⛔⛔ THE ONE PHRASING TWO SURFACES ALREADY PROMISE, AND IT ROUTED NOWHERE.
    # `agent device requests` tells a Windows user to type "/sr what am I waiting
    # on" and SKILL.md lists it as an example, and it reached the catch-all —
    # which denies having the verb. The subject gate below is what blocked it,
    # and that gate is right: 7.9-2 shipped a bare "waiting for …" that answered
    # every run-progress question. So this is not the gate coming off — it is one
    # more subject, and a narrow one. A WHOLE question about waiting, anchored at
    # the start of the message and naming nothing else, is not somebody asking
    # about a run; a person asking about a run names the run or its artefact, and
    # `_artefact_kw` above still excludes every one of those.
    _bare_waiting_q = re.match(r"^(?:so\s+)?(?:what|who)?\s*"
                               r"(?:am|are)\s+(?:i|we)\s+(?:still\s+)?"
                               r"waiting\s+(?:on|for)\b", low)
    if not _artefact_kw and (_request_kw or _machine_kw or _public_kw
                             or _bare_waiting_q) and (
            (_ask_kw and re.search(r"\b(my|any|outstanding|pending|open|all)\b.{0,24}"
                                   r"\b(requests?|asks?)\b", low))
            or re.search(r"\bwhat (?:did|have) i (?:ask|request)(?:ed)?\b", low)
            or re.search(r"\b(?:still )?waiting (?:on|for|to hear)\b", low)
            or re.search(r"\b(?:did|has|have) (?:anyone|anybody|they|the owner)\b"
                         r".{0,24}\b(?:answer|answered|reply|replied|respond|"
                         r"responded|approve|approved|said)\b", low)):
        # ⛔ THE OWNER'S BRANCH AND THE ASKER'S BRANCH ARE THE SAME COMMAND NOW.
        # It used to matter which one somebody meant, because only one of them
        # had an answer here; `device-requests` prints both halves, apart and
        # labelled, so either reading is served by the same reply.
        return ["device-requests"], None

    # ⭐ THE OBJECT DECIDES BETWEEN ASK AND BROWSE. A phrasing that names a
    # machine asks for THAT machine; one that names the category — "a public
    # computer", "someone else's machine" — is somebody looking for the list.
    _ask_obj = ""
    _om = (re.search(r"\bask\s+(?:the\s+)?owner\s+of\s+(.+?)\s+"
                     r"(?:for|about|to)\b", t, flags=re.I)
           or re.search(r"\b(?:ask|apply)\s+(?:the\s+owner\s+of\s+)?"
                        r"(?:for|to\s+use|about)\s+(.+)$", t, flags=re.I)
           or re.search(r"\brequest\s+(?:access\s+to\s+)?(.+)$", t, flags=re.I)
           or re.search(r"\bborrow\s+(.+)$", t, flags=re.I))
    if _om:
        _ask_obj = re.sub(r"[?.!,]+$", "", _om.group(1)).strip().strip(_NL_QUOTE_CHARS)
        # ⛔⛔ "access to" IS NOT PART OF THE NAME. "ask for access to the studio
        # pc" made the machine "access to the studio pc" and the confirm asked
        # somebody to disclose themselves to the owner of a computer that cannot
        # exist — then dead-ended on it. The sibling "request access to X" only
        # escaped because a different alternative strips it.
        _ask_obj = re.sub(r"^(?:access\s+to|use\s+of|permission\s+to\s+use|"
                          r"permission\s+to|permission\s+for|use)\s+", "",
                          _ask_obj, flags=re.I).strip()
        # ⛔ AND NEITHER IS POLITENESS. "ask for the Studio PC please" and
        # "…, if I can" carried the courtesy into the name and into the lookup.
        # ⛔⛤ THIS USED TO BE A PRIVATE LIST OF FIVE PHRASINGS AND IT WENT SHORT
        # BY FOUR — `today`, `now`, `pls` and `ok` all survived into the name.
        # It is the only site that had a politeness trim at all, which is why the
        # trim moved INTO the shared helper rather than being copied to the
        # other five. One list, one reader each.
        _ask_obj = _trim_trailing_clause(_ask_obj, t)
        _ask_obj = re.sub(rf"^{_NAME_DETERMINER}\s+", "", _ask_obj,
                          flags=re.I).strip()
        _ask_obj = _strip_leading_noun(_ask_obj)
    # ⛔ A PHASE OR AN ARTEFACT IS NOT A COMPUTER. "ask for the podcast" and
    # "ask for an update" belong to the rules below and must survive this one.
    _ask_obj_is_thing = bool(_artefact_kw) or bool(re.search(
        r"\b(podcasts?|audio|videos?|reports?|briefs?|links?|status|updates?|"
        r"progress|research(?:es)?|topics?|logs?|results?|files?)\b", _ask_obj, re.I))
    # ⛔ AND A PRONOUN IS NOT A NAME. "ask them to share it again" is advice this
    # product prints at people; reading it as a machine called "them" would turn
    # our own sentence into a request.
    _ask_obj_is_pronoun = bool(re.match(
        r"(?:them|him|her|it|us|me|you|somebody|someone|anyone|anybody)\b",
        _ask_obj, re.I))
    # ⛔⛔ THE WIDER NOUN LIST CANNOT GO IN HERE FLAT, AND A TEST CAUGHT IT. Four
    # of its words are also things people NAME a machine — "request access to that
    # Mac" means a specific one, and reading "Mac" as a category answered a named
    # ask with a list of everybody's machines. The narrow list this replaces
    # excluded them by accident; the split does it on purpose.
    # ⭐ THE DETERMINER IS THE TELL. "a mac", "public mac", "another mac",
    # "someone else's mac" are generic and take the browse list; a BARE "Mac", or
    # a deictic "that Mac", points at one row and keeps the consent question.
    # Words that can only ever be a category still match with no determiner.
    _CATEGORY_DET = (r"(?:public\s+|someone\s+else'?s?\s+|somebody\s+else'?s?\s+"
                     r"|another\s+|other\s+people'?s?\s+|shared\s+|a\s+|an\s+"
                     r"|the\s+)")
    # ⛔⛔ AND THE CAPTURE ABOVE HAS ALREADY EATEN THE DETERMINER THAT DECIDES IT.
    # `the|a|an|my|their|its|that|this` are stripped forty lines up, so "ask for a
    # mac" and "request access to that Mac" both arrive here as the same four
    # letters. The generic ones have to be read back off the original message; the
    # deictic ones (that/this) and the possessive ones (my/their/its) are the ones
    # deliberately NOT in this list, because each of them points at one machine.
    _ask_obj_generic_det = bool(
        _ask_obj and re.search(rf"\b(?:a|an|the|some|any)\s+{re.escape(_ask_obj.lower())}\b",
                               low))
    _ask_obj_is_category = bool(
        re.fullmatch(rf"{_CATEGORY_DET}*"
                     r"(?:computers?|machines?|devices?|pcs?|nodes?|laptops?"
                     r"|one|something|access|permission)",
                     _ask_obj, re.I)
        or re.fullmatch(rf"{_CATEGORY_DET}+(?:{_MACHINE_NOUNS})", _ask_obj, re.I)
        or (re.fullmatch(rf"(?:{_MACHINE_NOUNS})", _ask_obj, re.I)
            and _ask_obj_generic_det))
    # ⛔⛔ AND THE MESSAGE HAS TO BE ABOUT A MACHINE. The first draft accepted any
    # single word of six characters or more as "an id", so "ask for feedback",
    # "ask about pricing" and "request refund" all raised the consent question
    # that hands somebody's name to a stranger. An id here carries a separator;
    # an ordinary word does not.
    #
    # ⛔⛔ EXCEPT THAT A REAL ID CARRIES NO SEPARATOR, WHICH MADE THIS BRANCH DEAD.
    # `/api/devices/initiate-pair` mints `randomUUID().replace(/-/g, "")` — thirty-
    # two lowercase hex characters, no hyphen, no underscore — so the one shape the
    # app actually produces was the one shape this refused, and the three refusals
    # the branch exists to reach were unreachable. Somebody pasting the id from a
    # browse list got "I didn't catch a Super Research request in that."
    #
    # ⭐ THE SEPARATOR RULE STILL STANDS FOR EVERYTHING ELSE, because it is what
    # keeps "ask for feedback" out. Thirty-two hex characters is not an English
    # word and cannot become one, so admitting that exact shape widens nothing.
    _ask_obj_is_id = bool(
        " " not in _ask_obj
        and (re.fullmatch(r"[0-9a-fA-F]{32}", _ask_obj)
             or (len(_ask_obj) >= 8
                 and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*[-_]"
                                  r"[A-Za-z0-9_-]*[A-Za-z0-9]", _ask_obj))))
    _ask_is_about_a_machine = bool(
        _public_kw or _machine_kw or _ask_obj_is_id
        or re.search(r"\baccess to\b|\bto use\b|\bpermission\b|\bborrow\b", low))

    if _ask_kw and _ask_obj and _ask_is_about_a_machine and not _ask_obj_is_thing \
            and not _ask_obj_is_pronoun and not _ask_obj_is_category \
            and not _control_kw and not _unlink_kw:
        # ⛔ ONE ASK NAMES ONE OWNER. A request for a SET would file a disclosure
        # against every owner in it, and the confirm can only name one.
        if _request_names_a_set(t, _ask_obj):
            return None, ["I ask one owner at a time. Show me the public "
                          "computers and name the one you want — nothing is sent "
                          "until you do."]
        return None, [_NL_CONFIRMS["device-ask"].format(name=f"“{_ask_obj}”")]

    # Browse. ⛔⛔ IT NEEDS A BROWSING VERB. Without one this clause matched on
    # nothing but "a public word plus a machine word", which is true of run
    # controls, unlink requests, podcast asks and questions about the person's
    # own machine — every one of which it then answered with strangers' machines.
    if _artefact_kw or _control_kw or _unlink_kw or _mine_kw:
        pass
    elif _machine_kw and (_public_kw
                          or (_ask_kw and re.search(r"\bto use\b|\baccess\b|"
                                                    r"\bborrow\b|\bask for\b", low))):
        return ["devices-public"], None
    elif _public_kw and re.search(r"\b(find|browse|discover|see|show|list|what|which|"
                                  r"are there|any|available|offer(?:ed|ing)?)\b", low) \
            and re.search(r"\bcomputers?\b|\bmachines?\b|\bdevices?\b|"
                          r"\bones?\b|\bthem\b", low):
        return ["devices-public"], None

    # 3. Run controls (before the broad status rules).
    # ⛔⛔⛔ THE QUESTION GUARD EXISTED FOR ONE BRANCH OUT OF FIVE. `_q_start` was
    # written for skip because "skip is not confirm-gated" — and stop, pause,
    # resume and retry are the same, so `why did it pause` PAUSED THE RUN,
    # `is it safe to try again` RETRIED IT and `should i skip it` SKIPPED IT.
    # ⛔⛔ AND A RESEARCH TOPIC REACHED A DESTRUCTIVE CONFIRM, which is worse,
    # because this is a research product and people type topics:
    #   `i want to stop smoking`     -> Stop “smoking”?
    #   `how to stop smoking`        -> Stop “smoking”?
    #   `how do i stop a run`        -> Stop “a”?
    #   `what happens if i stop a run` -> Stop “a”?
    #   `stop asking me about my mac`  -> Stop “mac”?
    #   `please stop bothering me`     -> Stop “bothering me”?
    # ⭐⭐ SO THE FAMILY NEEDS TWO THINGS SKIP ALREADY HAD, AND ONE IT DID NOT:
    #   · the question guard (skip's own `_q_start`, hoisted verbatim);
    #   · skip's device-noun bail, so `stop asking me about my mac` is not a run;
    #   · A RUN SHAPE. A run-control verb with no run noun, no quoted title, no id
    #     and no `it/this/that` is not naming a run at all — it is a topic or a
    #     complaint, and the catch-all is the honest landing. `stop the tesla run`,
    #     `stop it`, `stop "All Reports"` and `pause run 3` all still fire.
    # ⭐ HOISTED OUT OF THE SKIP BLOCK ON 09-11 SO FIVE BRANCHES SHARE ONE COPY.
    # It was written for skip alone and stop/pause/resume/retry never saw it.
    # Two copies of a guard is how this file's noun lists drifted by two words.
    _q_start = re.match(
        r"\s*(why|is|are|did|does|has|have|what|when|where|who|how"
        # Modal-verb yes/no questions are ASKS, not orders: "can/could/should/
        # would/will/shall/may/do I skip the podcast?" must bail to a relay, not
        # silently skip a phase on the live run (skip is not confirm-gated).
        r"|can|could|should|would|will|shall|may|do|don't|dont)\b",
        low,
    )
    _device_noun = re.search(rf"\b({_MACHINE_NOUNS_SAID})\b", low)
    _runctl_question = _q_start or re.match(
        r"\s*(?:i\s+(?:want|need|would\s+like|wish)\s+to|how\s+to|what\s+happens)\b",
        low)
    _names_a_run = (re.search(r"\b(runs?|research(?:es)?|reports?|briefs?|job|task)\b", low)
                    or _NL_QUOTED_RE.search(t)
                    or re.search(r"\b(it|this|that|mine|everything|them)\b", low)
                    or re.search(r"\b\d+\b", low))
    # ⛔⛔ AND SKIP'S DEVICE-NOUN BAIL COULD NOT BE BORROWED AS-IS. I copied it
    # over and `pause the run on the shared machine` — which names a run in as
    # many words — bailed out of pause, FELL THROUGH TO THE SWITCH BRANCH and
    # EXECUTED `device-use`: worse than the defect, because it acts on the wrong
    # feature instead of the right one. Skip's bail is safe there because nothing
    # below skip claims those words. The A/B against the pre-build revision is the
    # only reason I saw it. So the device noun disqualifies a run-control verb
    # ONLY when no run is named: `stop asking me about my mac` has no run and
    # bails; `stop the run on the public computer` has one and fires.
    # ⛔ A BARE VERB NAMES THE CURRENT RUN, and the run-shape test refused it:
    # `retry` on its own came back with the catch-all, and a test demands it work.
    _runctl_bare = re.fullmatch(
        r"(?:please\s+|just\s+|now\s+|ok\s+|can\s+you\s+)*"
        r"(?:stop|end|abort|cancel|pause|hold on|hold it|resume|unpause|retry|"
        r"try again|skip)(?:\s+(?:please|now|it))?", low)
    _names_a_run = _names_a_run or _runctl_bare
    _runctl_ok = (not _runctl_question and bool(_names_a_run)
                  and not (_device_noun and not _names_a_run))
    # ⛔⛔⛔ AND WHEN A RUN-CONTROL VERB IS PRESENT BUT ITS BRANCH BAILS, THE MESSAGE
    # MUST NOT REACH A DIFFERENT MUTATING BRANCH. This is the third and fourth time
    # in one wave that a veto handed work to the wrong feature, and cross-verify
    # found these two after the harness was green:
    #   `pause and switch to the Studio PC` -> EXECUTED `device-use`, pause dropped
    #   `stop and remove the video`         -> EXECUTED `skip video`, stop dropped
    # Both are compound asks naming two acts; silently doing the second one is
    # worse than asking. ⭐ It gates only the branches BELOW that mutate — the run
    # branches themselves still fire whenever they can, and `skip the podcast on my
    # computer` still reaches skip's own second branch, which is bare and correct.
    # ⛔ ONE LIST FOR THE STOP VERBS, read three times in four lines.
    # ⛔⛔ AND `drop` IS NOT IN IT, THOUGH I PUT IT THERE FIRST. `drop` is
    # THREE-WAY ambiguous on this surface — drop a run, drop a machine, drop a
    # phase — and the skip branch already owns the third. Adding it here stole
    # `drop ChatGPT from the research` from skip and offered to stop a run called
    # “ChatGPT from the”. Two existing tests caught it. A shared verb is settled
    # by its OBJECT, and here the object that matters is a machine: `drop my
    # Studio PC` unlinks, exactly as `remove` does. The run side stays with skip.
    _stop_verbs = r"(?:stop|end|abort|cancel)"
    # ⛔⛤ ONE TRIGGER PATTERN PER VERB, READ BY THE BRANCH AND BY ITS OWN TAIL
    #    STRIP. Written separately, the condition knew the multi-word forms and
    #    the strip did not — so the trigger phrase stayed in the message and
    #    became the run TITLE. Every one of these is a phrasing SKILL.md teaches:
    #      `hold on`                  -> ['pause', 'hold on']
    #      `continue the paused run`  -> ['resume', 'continue the paused']
    #      `that's enough`            -> Stop “that's enough”?
    #    The person named no run; the client quoted their own words back as one.
    _T_STOP = rf"(?:{_stop_verbs[3:-1]}|that.?s\s+enough)"
    _T_PAUSE = r"(?:pause|hold\s+(?:on|it))"
    _T_RESUME = r"(?:resume|unpause|continue\s+the\s+paused(?:\s+run)?)"
    _T_RETRY = r"(?:retry|try\s+again)"
    _runctl_verb = re.search(rf"\b(?:{_stop_verbs[3:-1]}|pause|resume|unpause|retry)\b", low)
    _runctl_dropped = bool(_runctl_verb) and not _runctl_ok
    if re.search(rf"\b{_T_STOP}\b", low) and _runctl_ok:
        name = _nl_run_name(t, re.sub(rf"^.*?\b{_T_STOP}\b", "", t, flags=re.I).strip())
        # ⛔ STOP HAD NO MESSAGE-LEVEL CHECK AT ALL. Measured: `stop all of my
        # research` came back "Stop the current run?", `stop all my research on
        # tesla` came back `Stop “tesla”?` and `stop all three runs`
        # confirmed — three ways to ask for every run and three confident
        # single-run answers.
        # ⭐ AND QUOTING STILL WINS: `stop "All Reports"` names a run title, and
        # the quoted span is blanked before the signal is looked for.
        if _request_names_a_set(t, name):
            return None, ["I stop one run at a time. Ask me to list the running "
                          "ones and name it — nothing is stopped until you do."]
        return None, [_NL_CONFIRMS["stop"].format(name=f"“{name}”" if name else "the current run")]
    if re.search(rf"\b{_T_PAUSE}\b", low) and _runctl_ok:
        name = _nl_run_name(t, re.sub(rf"^.*?\b{_T_PAUSE}\b", "", t, flags=re.I).strip())
        # ⛔ THE SAME GATE AS STOP. These three end in an honest "No run matching"
        # when handed a set, so 7.9-5 graded them minor — but `stop all my runs`
        # refusing while `pause all my runs` does not is an inconsistency a person
        # reads as one of the two being broken, and it is one line each.
        if _request_names_a_set(t, name):
            return None, ["I pause one run at a time. Ask me to list the running "
                          "ones and name it — nothing changes until you do."]
        return ["pause"] + ([name] if name else []), None
    if re.search(rf"\b{_T_RESUME}\b", low) and _runctl_ok:
        name = _nl_run_name(t, re.sub(rf"^.*?\b{_T_RESUME}\b", "", t, flags=re.I).strip())
        # ⛔ THE SAME GATE AS STOP. These three end in an honest "No run matching"
        # when handed a set, so 7.9-5 graded them minor — but `stop all my runs`
        # refusing while `pause all my runs` does not is an inconsistency a person
        # reads as one of the two being broken, and it is one line each.
        if _request_names_a_set(t, name):
            return None, ["I resume one run at a time. Ask me to list the running "
                          "ones and name it — nothing changes until you do."]
        return ["resume"] + ([name] if name else []), None
    if re.search(rf"\b{_T_RETRY}\b", low) and _runctl_ok:
        name = _nl_run_name(t, re.sub(rf"^.*?\b{_T_RETRY}\b", "", t, flags=re.I).strip())
        # ⛔ THE SAME GATE AS STOP. These three end in an honest "No run matching"
        # when handed a set, so 7.9-5 graded them minor — but `stop all my runs`
        # refusing while `pause all my runs` does not is an inconsistency a person
        # reads as one of the two being broken, and it is one line each.
        if _request_names_a_set(t, name):
            return None, ["I retry one run at a time. Ask me to list the running "
                          "ones and name it — nothing changes until you do."]
        return ["retry"] + ([name] if name else []), None
    # skip / drop phases or P2 agents ("skip the video and the report",
    # "remove the video", "no email", "skip Claude in P2"). Guards (review
    # catches — skip is NOT confirm-gated, so a mis-route silently
    # reconfigures a live run):
    #   • questions bail ("did claude skip anything?" is not an order);
    #   • device nouns bail ("remove claude's laptop" = device-remove, which
    #     keeps its confirm);
    #   • agent nouns need the verb ADJACENT ("skip claude"), never bare
    #     co-occurrence, never a possessive/compound ("claude's", "claude-pc"),
    #     and never when folded into a phase noun ("the gemini video" is the
    #     video, not the agent);
    #   • a research ask in the same message bails ("no gpt needed, research
    #     solar panels" must not eat the research and drop ChatGPT).
    # ⛔⛔ THE RUN NAME. Wave 1.2 measured that a person CANNOT skip a phase of any
    #    run but the newest active one, from chat, at all — nineteen phrasings all
    #    dropped the name and reconfigured whichever run was newest. The branch
    #    had exactly two returns and neither ever appended `--run`; the capability
    #    exists only at the raw CLI. It is emitted as `--run=<name>` in ONE token
    #    because the relay splits flags from positionals by membership.
    # ⛔⛤ AND IT IS CAPTURED NARROWLY, NOT BY THE SHARED RUN-NAME HELPER. That
    #    helper falls back to "everything after the verb", which here is the PHASE
    #    LIST: `skip the video and the report` came out naming a run called
    #    “video and the report”. A skip names a run in exactly two ways — a quoted
    #    title, or an explicit `on|for|of <title> run` — and anything else is the
    #    phases, which is why this is a shape test and not a fallback.
    # ⛔⛤ THE `called|named|titled` SHAPE IS READ FIRST, because the `<name> run`
    #    shape eats it: `skip the podcast on run called Deep Research` came out
    #    naming a run “run called Deep”. And the `<name> run` capture rejects a
    #    bare determiner — `skip the podcast on the run` named a run “the”, which
    #    then SUBSTRING-MATCHED an arbitrary run and skipped a phase of it.
    _skip_rm = (_NL_QUOTED_RE.search(t)
                or re.search(r"\brun\s+(?:called|named|titled)\s+"
                             r"([\w'\u2019 -]+?)\s*$", t, re.I)
                or re.search(r"\b(?:on|for|in|of)\s+(?:the\s+|my\s+)?"
                             r"((?!(?:the|a|an|my|our|this|that|current|latest|"
                             r"last|newest|run|research)\b)[\w'\u2019 -]+?)"
                             r"\s+(?:run|research)\b", t, re.I)
                # ⛔ AND WITHOUT A PREPOSITION: `skip the Mars run` names a run
                #    and no phase, which is what the bare form is for.
                # ⛔⛤ THE TITLE CARRIES NO PREPOSITION OF ITS OWN. A space-tolerant
                #    capture reached ACROSS one — `skip the podcast on the run`
                #    came out naming a run “podcast on the” — so each word after
                #    the first is guarded, not only the first.
                or re.search(r"\b(?:the|my)\s+"
                             r"((?!(?:the|a|an|my|our|this|that|current|latest|"
                             r"last|newest|run|research)\b)[\w'\u2019-]+"
                             r"(?:\s+(?!(?:on|for|in|of|the|a|an|my|our|this|that)\b)"
                             r"[\w'\u2019-]+)*?)"
                             r"\s+(?:run|research)\b", t, re.I))
    _skip_run = _skip_rm.group(1).strip() if _skip_rm else None
    # ⛔⛤ AND A PHASE WORD IS NOT REJECTED HERE, THOUGH I REJECTED ONE FIRST.
    #    All three shapes above are EXPLICIT run-naming — a quoted title, an
    #    `on|for|of <title> run`, a `run called <title>` — so a run genuinely
    #    called “brief” is named by the only means the product offers, and
    #    throwing it away sent the skip to the NEWEST run instead. The guard was
    #    written for the loose fallback this capture replaced; it outlived its
    #    reason, and the mutation harness is what showed the difference.
    #    What still disqualifies a capture is a GENERIC reference or a bare
    #    machine noun, neither of which is a title anybody typed.
    if _skip_run and (_skip_run.lower() in _NL_GENERIC_RUN
                      or _is_bare_machine_noun(_skip_run)):
        _skip_run = None
    _run_flag = [f"--run={_skip_run}"] if _skip_run else []

    # ⛔⛔ A QUESTION ABOUT SKIPPING IS NOT AN ORDER, AND BAILING IS NOT ENOUGH.
    #    `can i skip the podcast` fell past both branches and reached the PODCAST
    #    branch, which DOWNLOADS THE AUDIO. This returns the catch-all rather than
    #    handing the message on — the lesson wave 1.1 paid for four times.
    # ⛔ THE INFLECTIONS TOO — `is the podcast skipped` is a question about a
    #    phase and it reached the PODCAST branch, which downloads the audio.
    # ⛔⛤ AND THE QUESTION TEST HERE IS NOT ANCHORED AT CHARACTER 0. `_q_start` is
    #    a `re.match`, so `please could you skip the brief`, `hey can you skip the
    #    video`, `btw can i skip the podcast` and a dozen more preambles defeated
    #    it and POSTED A REAL SKIP. Skip is not confirm-gated; there is no second
    #    chance. The lead-in vocabulary this file already keeps is the fix.
    # ⛔ AND THE SUBJECT IS WHAT SEPARATES A QUESTION FROM A POLITE ORDER.
    #    `could YOU skip the brief` is an order — this file already has
    #    `_polite_imperative` for that shape on the visibility surface — while
    #    `can I skip the podcast` and `should WE skip the video` are asks. My
    #    first version read both as questions and refused the order too.
    # ⛔ AND A POLITE ORDER IS NOT A QUESTION, however it opens: `would you skip
    #    the report` and `can you skip the video` are instructions to the
    #    assistant, and `_q_start` reads their first word as a question opener.
    _polite_skip_order = re.match(
        rf"{_NL_LEAD_IN}(?:can|could|would|will|please|do)\s+(?:you\s+)?"
        rf"(?:please\s+)?(?:skip|drop)\b", low)
    _skip_question = (not _polite_skip_order) and (bool(_q_start) or bool(re.match(
        r"\s*(?:please|hey|hi|ok|okay|so|also|btw|hmm+|um+|well|"
        r"quick question|question|tell me|i wonder|i was wondering|"
        r"just wondering|any chance|by the way)\b[\s,:;-]*"
        r"(?:\w+\s+){0,3}?"
        r"(?:\b(?:can|could|should|would|shall|may|do|did|does|is|are|am)\s+"
        r"(?:i|we)\b|\b(?:i|we)\s+"
        r"(?:can|could|should|would|shall|may|ought)\b)",
        low)) or bool(re.match(
        r"\s*(?:please|hey|hi|ok|okay|so|also|btw|hmm+|um+|well|"
        r"quick question|question|tell me|i wonder|i was wondering|"
        r"just wondering|any chance|by the way)\b[\s,:;-]*"
        r"(?:\w+\s+){0,3}?"
        r"\b(?:what|which|why|when|where|who|how|is|are|did|does|has|have)\b",
        low)))
    if _skip_question and re.search(r"\bskip(?:s|ped|ping)?\b|\bdrop(?:s|ped|ping)?\b", low) and \
            re.search(rf"\b(?:{'|'.join(_NL_PHASE_WORDS)}|"
                      rf"{'|'.join(_NL_AGENT_WORDS)}|phase|step|blocker)\b", low):
        return None, [_NL_CATCH_ALL]
    # ⛔ `skip nothing` IS NOT A SKIP. It reached the bare form and resolved the
    #    run's blocker — the one thing it says not to do.
    if re.search(r"\bskip\s+(?:nothing|none|neither)\b", low):
        return None, [_NL_CATCH_ALL]

    # skip / drop phases or P2 agents ("skip the video and the report",
    # "remove the video", "no email", "skip Claude in P2"). Guards (review
    # catches — skip is NOT confirm-gated, so a mis-route silently
    # reconfigures a live run):
    #   • questions bail ("did claude skip anything?" is not an order);
    #   • device nouns bail ("remove claude's laptop" = device-remove, which
    #     keeps its confirm) — UNLESS a phase word sits right after the verb;
    #   • agent nouns need the verb ADJACENT ("skip claude"), never bare
    #     co-occurrence, never a possessive/compound ("claude's", "claude-pc"),
    #     and never when folded into a phase noun ("the gemini video" is the
    #     video, not the agent);
    #   • a research ask in the same message bails ("no gpt needed, research
    #     solar panels" must not eat the research and drop ChatGPT).
    # ⛔⛔ THE DEVICE BAIL IS CONDITIONAL NOW. `skip the podcast on my computer`
    #    bailed here and branch 2 returned the bare form, which resolves the run's
    #    BLOCKER — the person named a phase and got a different mutation. The
    #    machine in that sentence is WHERE, not WHAT. The bail still stands when
    #    no phase follows the verb, which is what keeps `remove claude's laptop`
    #    a device-remove with its confirm.
    # ⛔ AND THE PHASE WORD MUST NOT ITSELF BE PART OF A MACHINE NAME.
    #    `remove my video PC` names a computer called “video PC”; without the
    #    lookahead it read as "skip the video" and reconfigured a live run
    #    instead of asking to unlink a machine — which is the very swap the
    #    device bail was written to prevent, reintroduced by the exception to it.
    _phase_is_the_object = re.search(
        rf"\b(?:skip(?:ping)?|drop(?:ping)?|remove|cut|leave\s+out|without|no)\s+"
        rf"(?:{_NAME_DETERMINER}\s+)?(?:{'|'.join(_NL_PHASE_WORDS)})\b"
        rf"(?!\s+(?:{_MACHINE_NOUNS_SAID})\b)", low)
    if not _skip_question and (not _device_noun or _phase_is_the_object) \
            and not _runctl_dropped and \
            re.search(r"\bskip(?:s|ping)?\b|\bdrop(?:s|ping)?\b|"
                      r"\b(remove|cut|leave out|without|no)\b", low):
        # ⛔⛔ THE EXCLUSION INVERTS ITSELF WITHOUT THIS. `skip all but the
        #    podcast` skipped THE PODCAST — the one thing the person said to
        #    keep — because the phase words were collected by presence. An
        #    exclusion names the KEEPER; what is skipped is everything else, and
        #    "everything else" is derived from the command's own phase map.
        # ⛔⛤ THE RUN NAME IS NOT A PHASE LIST, AND CHASING A MUTATION SURVIVOR
        #    FOUND THIS ONE. `skip the report for the brief run` came out
        #    `['skip','brief','report']` — it skipped the BRIEF as well, because
        #    the phase scan read the whole message and the run is CALLED brief.
        #    The span the run name came from is blanked before the scan.
        _scan = low
        if _skip_rm:
            _scan = low[:_skip_rm.start()] + " " + low[_skip_rm.end():]
        # ⛔⛔⛔ ONE EXCLUSION READER, AND CROSS-VERIFY MEASURED WHY. The first
        #    version knew ONE shape and ONE keeper, and everything else inverted:
        #      `skip all but phase 3`             SKIPPED PHASE 3 — a perfect inversion
        #      `skip all but claude and gemini`   TURNED OFF BOTH KEEPERS
        #      `skip all but the podcast and the brief`  skipped the brief
        #      `skip the video but keep the report`      skipped the report
        #      `skip the podcast but not the video`      skipped the video
        #    An exclusion names what to KEEP. Two shapes say it, and both have to
        #    read EVERY keeper after the word, across all three domains — phase
        #    words, phase numbers and agents.
        #      COMPLEMENT   `skip ALL but X`  -> everything except X
        #      SUBTRACTIVE  `skip A but keep B` -> A minus B
        _excl = re.search(r"\b(?:but|except|apart\s+from|other\s+than|excluding)\s+"
                          r"(?:not\s+|leave\s+|keep\s+)?(.+)$|"
                          r"\b(?:keep|leave|save)\s+(.+)$", _scan)
        if _excl:
            _tail = _excl.group(1) or _excl.group(2) or ""
            _head = _scan[:_excl.start()]
            _keep_phases = {_SKIP_NAMES[w] for w in _NL_PHASE_WORDS
                            if re.search(rf"\b{w}\b", _tail)}
            _keep_phases |= {int(n) for n in re.findall(r"\b(\d+)\b", _tail)
                             if int(n) in _SKIP_PHASE_NUMBERS}
            _keep_agents = {_SKIP_AGENTS[a] for a in _NL_AGENT_WORDS
                            if re.search(rf"\b{a}\b", _tail)}
            _totaliser = re.search(r"\b(?:all|everything|every\s+phase|"
                                   r"the\s+(?:rest|lot|whole\s+thing))\b", _head)
            _order = {w: i for i, w in enumerate(_SKIP_NAMES)}

            def _one_per_number(nums):
                seen_n: set = set()
                return [w for w in sorted(_NL_PHASE_WORDS,
                                          key=lambda w: (_SKIP_NAMES[w], _order[w]))
                        if _SKIP_NAMES[w] in nums
                        and not (_SKIP_NAMES[w] in seen_n
                                 or seen_n.add(_SKIP_NAMES[w]))]

            if _totaliser and (_keep_phases or _keep_agents):
                # ⛔ THE DOMAIN IS WHICHEVER ONE THE KEEPER NAMES. `skip all but
                #    chatgpt` is about AGENTS, and complementing phases there
                #    would turn off everything the person did not mention.
                if _keep_agents and not _keep_phases:
                    _out = sorted(set(_SKIP_AGENTS.values()) - _keep_agents)
                else:
                    _out = _one_per_number(set(_SKIP_PHASE_NUMBERS) - _keep_phases)
                if not _out:
                    return None, [_NL_CATCH_ALL]
                # ⛔ AND THE SET GATE STILL SEES THE HEAD. Blanking the whole
                #    exclusion span took `all my runs` with it, so
                #    `skip the podcast on all my runs but the brief` executed on
                #    ONE run. Only the keeper tail is the exclusion's.
                # ⛔ AND THE TOTALISER ITSELF IS THE EXCLUSION'S WORD, not a set
                #    of runs — `skip everything except the brief` was refused as
                #    a bulk RUN ask because "everything" survived into the head.
                #    It is blanked, and anything else that makes the head a set
                #    (`all my runs`) is not.
                if _request_names_a_set(
                        _head[:_totaliser.start()] + " " + _head[_totaliser.end():],
                        _skip_run):
                    return None, [_NL_SKIP_ONE_RUN]
                return ["skip"] + _run_flag + _out, None
            if _keep_phases or _keep_agents:
                _said_p = {_SKIP_NAMES[w] for w in _NL_PHASE_WORDS
                           if re.search(rf"\b{w}\b", _head)}
                _said_a = {_SKIP_AGENTS[a] for a in _NL_AGENT_WORDS
                           if re.search(rf"\b{a}\b", _head)}
                _out = _one_per_number(_said_p - _keep_phases) + \
                    sorted(_said_a - _keep_agents)
                if _out:
                    if _request_names_a_set(_head, _skip_run):
                        return None, [_NL_SKIP_ONE_RUN]
                    return ["skip"] + _run_flag + _out, None
                return None, [_NL_CATCH_ALL]
        # ⛔ EMITTED IN PHASE ORDER, NOT MATCH ORDER — the matching list is sorted
        #    longest-first so "chatgpt" beats its own substring "gpt", and reusing
        #    that order here reversed `skip the video and the report`.
        _order = {w: i for i, w in enumerate(_SKIP_NAMES)}
        _hits = [w for w in _NL_PHASE_WORDS if re.search(rf"\b{w}\b", _scan)]
        seen_n = set()
        phases = [w for w in sorted(_hits, key=lambda w: (_SKIP_NAMES[w], _order[w]))
                  if not (_SKIP_NAMES[w] in seen_n or seen_n.add(_SKIP_NAMES[w]))]
        # ⛔⛔ PHASE NUMBERS WERE UNROUTABLE AND LANDED ON A MUTATION. `skip phase
        #    3`, `skip 4 and 5` and `skip step 2` all reached the bare form, which
        #    resolves the run's BLOCKER. The CLI has accepted numbers all along.
        _nums: list = []
        # ⛔⛤ AND IT READS THE BLANKED COPY, as the phase-word scan does. Reading
        #    `low` made a number inside a RUN TITLE a phase: `skip phase 3 for the
        #    2024 run` was refused as “Phase 2024”, and `skip the video on
        #    "Phase 3 Review"` skipped phase 3 as well.
        # ⛔ A BARE NUMBER AFTER `skip` IS A PHASE — the refusal this command
        #    prints names the numbers, so it invites exactly `skip 3`, and that
        #    reached the bare arm and RESOLVED THE BLOCKER instead.
        if re.fullmatch(r"(?:please\s+|just\s+)*(?:skip|drop)\s+"
                        r"\d+(?:\s*(?:,|and|&)\s*\d+)*[.!]*", _scan):
            _nums = re.findall(r"\b(\d+)\b", _scan)
        elif re.search(r"\b(?:phases?|steps?|p)\s*\d", _scan):
            # ⛔ EVERY NUMBER IN THE LIST, not only the one beside the word.
            #    `skip phase 4 and 5` skipped 4 and silently dropped 5.
            _tail = _scan[re.search(r"\b(?:phases?|steps?|p)\s*\d", _scan).start():]
            _nums = re.findall(r"\b(\d+)\b", _tail)
        _nums = _nums or []
        _bad = [n for n in _nums if int(n) not in _SKIP_PHASE_NUMBERS]
        if _bad:
            # ⛔ AND AN UNSKIPPABLE NUMBER IS REFUSED BY NAME. `skip step 2` found
            #    no phase, fell to the bare arm and RESOLVED THE RUN'S BLOCKER —
            #    a mutation the person never asked for. The list it names is the
            #    command's own map, so it cannot go stale.
            _menu = ", ".join(f"{n} ({'/'.join(sorted(w for w in _SKIP_NAMES if _SKIP_NAMES[w] == n))})"
                              for n in _SKIP_PHASE_NUMBERS)
            return None, [f"Phase {_bad[0]} isn’t one I can skip. The ones I can: "
                          f"{_menu}."]
        for _n in _nums:
            if _n not in phases:
                phases.append(_n)
        agents: list = []
        # ⛔ THE AGENT MAY FOLLOW A CONJUNCTION, NOT ONLY THE VERB.
        #    `skip chatgpt and the video` turned ChatGPT off; `skip the video and
        #    chatgpt` — the same ask, said the other way round — silently did not.
        _agent_adjacent = re.search(
            rf"\b(?:skip(?:ping)?|drop(?:ping)?|remove|cut|leave\s+out|without|minus|no)\s+"
            rf"(?:[^.?!]{{0,28}}?\b(?:and|or|,|plus|as\s+well\s+as)\s+)?"
            rf"(?:{_NAME_DETERMINER}\s+|any\s+)?(?:{'|'.join(_NL_AGENT_WORDS)})\b(?!['’-])"
            rf"(?!\s+(?:{'|'.join(_NL_PHASE_WORDS)})\b)", low)
        if _agent_adjacent and not re.search(r"\b(?:research|look into|deep dive on|investigate)\s+\w+", low):
            agents = [_SKIP_AGENTS[a] for a in _NL_AGENT_WORDS
                      if re.search(rf"\b{a}\b(?!['’-])"
                                   rf"(?!\s+(?:{'|'.join(_NL_PHASE_WORDS)})\b)", low)]
            agents = sorted(dict.fromkeys(agents))
        if phases or agents:
            # ⛔⛔ AND THE SET GATE. This was the ONLY mutating act branch with no
            #    set gate on its phase arm: `skip the podcast on all my runs`
            #    applied it to ONE run and said nothing. The bare arm below has
            #    had the gate since 1.1; the two arms now answer alike.
            if _request_names_a_set(t, _skip_run):
                return None, [_NL_SKIP_ONE_RUN]
            return ["skip"] + _run_flag + phases + agents, None
    # ⛔⛔ BRANCH 2 HAD NEITHER GUARD, AND IT IS THE ONE THAT ACTUALLY FIRES for a
    # bare `skip`. `_q_start` above gates branch 1 only, so `should i skip it`
    # SKIPPED A PHASE ON A LIVE RUN — and skip is not confirm-gated, so there was
    # no second chance. ⛔ It is also the ONLY mutating act branch in the ladder
    # with no set gate at all: `skip all my runs`, `skip every run` and
    # `skip both my runs` each executed the bare single-target form against
    # whichever run it happened to land on, while pause, resume, retry and stop
    # all refuse the same phrasing. The set gate is one line, and it is the same
    # line those four already have.
    # ⛔⛔ AND BRANCH 2 MUST NOT GET BRANCH 1'S DEVICE-NOUN BAIL. I gave it one and
    # broke `skip the podcast on my computer`: branch 1 bails on the device noun BY
    # DESIGN (so a device message cannot extract a PHASE), branch 2 then catches it
    # and returns a bare `skip`, which is right. Bailing here too sent the message
    # on to the PODCAST branch, which FETCHED THE PODCAST. Branch 2 emits no phase,
    # so it never needed the bail — the existing suite caught this, and it is the
    # third time in this one change that a veto turned into a hand-off to the wrong
    # branch. ⭐ A VETO IN AN ORDERED LADDER IS NOT INERT: it gives the message to
    # whatever comes next, and that has to be checked every single time.
    # ⛔⛤ AND THE BARE ARM NEEDS A GENERIC OBJECT, NOT JUST THE WORD `skip`.
    #    Written as `^skip\b` it fired on ANY object it did not recognise —
    #    `skip the summary`, `skip the sources`, `skip the transcript`,
    #    `skip the pdf`, `skip my computer` — and the bare form RESOLVES THE
    #    RUN'S CURRENT BLOCKER, a mutation none of them asked for.
    # ⛔ THE SET REFUSAL COMES FIRST AND DOES NOT DEPEND ON THE OBJECT. Narrowing
    #    the bare arm's object sent `skip all my runs` to the CATCH-ALL, which
    #    says nothing about the thing being asked for; the refusal says skip works
    #    one run at a time, which is the answer. An existing test caught it.
    if re.search(r"\bskip(?:s|ping)?\b|\bdrop(?:s|ping)?\b", low) \
            and not _skip_question and _request_names_a_set(t, _skip_run):
        return None, [_NL_SKIP_ONE_RUN]
    # ⛔ AND A NAMED RUN WITH NO PHASE IS A BARE SKIP ON THAT RUN. `skip the Mars
    #    run` reached the catch-all: it names a run and no phase, which is exactly
    #    what the bare form is for — resolve THAT run's blocker, not the newest.
    if (re.fullmatch(r"(?:please\s+|just\s+|now\s+|ok\s+)*skip"
                     r"(?:\s+(?:it|this|that|the\s+step|the\s+blocker|"
                     r"the\s+current\s+one|ahead|forward|please|now))*[.!]*", low)
            or re.search(r"\bskip (it|this|that|the step|the blocker)\b", low)
            or (_skip_run and re.match(rf"{_NL_LEAD_IN}skip\b", low))) \
            and not _skip_question:
        if _request_names_a_set(t, _skip_run):
            return None, [_NL_SKIP_ONE_RUN]
        return ["skip"] + _run_flag, None

    # 4. Devices.
    # ⛔⛔ THE LIST CLAUSE READ ONLY `devices?|nodes?`, SO FIVE OF THE TEN WORDS
    # THIS PRODUCT USES FOR A MACHINE MISSED IT: "show my computers", "which
    # machines do I have" and "which pcs do I have" all reached the catch-all,
    # which then told the reader it could "manage your devices" — the very thing
    # it had just failed to do. The list it reads is the shared one now.
    # ⛔⛔ AND WIDENING IT ALONE WOULD HAVE BROKEN THE VERBS BELOW IT. This clause
    # sits ABOVE the switch and remove branches, so "remove my node" has always
    # printed the device list instead of offering to unlink — measured and left
    # alone in 7.9-3 because the ordering predates those verbs. With every noun in
    # the clause, "remove my mac" and "remove my computer" would have joined it.
    # The gate is the ACTION, not the noun: a message carrying a device verb is
    # not a request to list them, and the pre-existing defect closes with it.
    # ⛔ `use` IS DELIBERATELY NOT IN THE GATE. Its own branch below is gated on a
    # QUOTED name, so excluding "use my mac" here would drop it past every device
    # rule to the catch-all — strictly worse than answering with the list.
    # ⛔⛔ AND IT MUST BAIL ON AN ARTEFACT TOO, WHICH THE NARROW LIST HID. "ask
    # for the podcast on my computer" and "ask for an update on my machine" carry
    # both a possessive and a machine word; with `computers?|machines?` in the
    # clause they became requests to list devices, and the podcast and status
    # rules below never saw them. `_artefact_kw` is the same guard rule 2d uses,
    # and it already blanks "research computer" before looking.
    # ⛔⛔ AND THE ARTEFACT GATE BELONGS ONLY TO THE WORDS THIS WAVE ADMITTED.
    # Applying it to the whole clause dropped questions that worked at HEAD into
    # the catch-all that boasts it can "manage your devices" — measured:
    # "which device is my run on", "list my devices and runs", "show me the
    # devices with my research" and "show me my devices and their status" all
    # carry an artefact word AND the narrow noun, and all four are plainly
    # inventory questions. The narrow half keeps HEAD's behaviour exactly; only
    # the widened half has to prove it is not really about a podcast or a run.
    # ⛔⛔ AND `run on` NEEDS AN OBJECT. Written bare it matched "which device is my
    # run ON" — a plain inventory question — and dropped it into the catch-all,
    # because this gate is consulted before the clause it protects. Cross-verify
    # measured it; at HEAD the narrow clause answered it before any switch rule
    # could see it.
    # ⛔ `drop` BELONGS HERE TOO, or the list branch above takes it: `drop my
    # Studio PC` answered with the DEVICE LIST because `my … PC` reads as a list
    # request, and the unlink branch that would have handled it sits below.
    _dev_verb = re.search(rf"\b(?:{_UNLINK_VERBS[3:-1]}|add|pair|connect|"
                          rf"switch to)\b|\brun (?:it |everything )?on\s+\S", low)
    _list_narrow = re.search(r"\b(which|what|list|show|my)\b.*\b(devices?|nodes?)\b", low)
    _list_wide = re.search(rf"\b(which|what|list|show|my)\b.*\b({_MACHINE_NOUNS_SAID})\b", low)
    # ⛔ `running` IS NOT IN `_artefact_kw` AND HAD TO BE NAMED. "what's running on
    # my mac" is a question about RUNS; at HEAD the narrow list let it fall through
    # to the progress rule, and the wider one caught it.
    _wide_is_clean = (not _artefact_kw and not _control_kw
                      and not re.search(r"\brunning\b", low))
    if (not _dev_verb and (_list_narrow or (_list_wide and _wide_is_clean))) or \
            low in ("devices", "device list") or "what am i running on" in low:
        return ["devices"], None
    # ⛔ THE DETERMINER LIST IS THE SHARED ONE. Spelled `the|my` here and
    # `the|a|an|my|their|its|that|this` at unlink, this branch carried the
    # determiner INTO the name: `switch to that mac`, `to their laptop` and
    # `to this computer` all EXECUTED — no confirm — on a string no lookup can
    # resolve. Same question, same answer, one list.
    m = re.search(rf"\b(?:switch to|run (?:it |everything )?on|use)\s+"
                  rf"(?:{_NAME_DETERMINER}\s+)?(.+)$", t, flags=re.I)
    # ⛔ `use` IS IN THE GATE NOW BECAUSE IT WAS ALWAYS IN THE CAPTURE. The
    # picker one file up ends every ask with 'Just say: use “<name>”.' — the one
    # phrasing this line did not route, so following the instruction on screen
    # reached "I didn't catch a Super Research request in that". It is gated on a
    # QUOTED name so that "use less video" and "use chatgpt" stay clear of it.
    # ⛔⛤ AND UNQUOTED TOO, WHEN WHAT FOLLOWS IS A MACHINE AND NOT A SETTING.
    #     `use "Studio PC"` worked and `use Studio PC` reached the catch-all, so
    #     following the picker's instruction worked only if you typed the quotes
    #     it printed. The gate that kept `use less video` and `use chatgpt` out is
    #     what the word list below does — an artefact, an agent or a phase word
    #     after `use` is not a machine.
    # ⛔⛔ AND THE UNQUOTED OBJECT MUST LOOK LIKE A MACHINE. Cross-verify drove
    # 24 of 24 ordinary objects into an UNCONFIRMED device switch: `use the web`,
    # `use plain english`, `use bullet points`, `use dark mode`, `use google`,
    # `use my judgment` all repointed where every future run would execute. A
    # stop-list of phase and agent words cannot cover the English language; the
    # object has to carry a machine noun or be an identifier.
    _use_obj = re.sub(rf"^use\s+(?:{_NAME_DETERMINER}\s+)?", "", t, flags=re.I).strip()
    _bare_use = t[:4].lower() == "use " and (
        t[4:5] in _NL_QUOTE_CHARS
        or bool(re.search(rf"\b(?:{_MACHINE_NOUNS_SAID})\b", _use_obj, re.I)
                or _looks_like_a_machine_token(_use_obj))
        and bool(re.fullmatch(
            rf"use\s+(?:{_NAME_DETERMINER}\s+)?"
            rf"(?!(?:{'|'.join(_NL_PHASE_WORDS)}|{'|'.join(_NL_AGENT_WORDS)}|"
            rf"less|more|fewer|another|it|this|that|them|one)\b)"
            rf"[\w'\u2019-]+(?:\s+[\w'\u2019-]+){{0,3}}", low)))
    # ⛔⛔ THE QUESTION GUARD REACHES HERE TOO, AND IT HAD TO. This branch mutates
    # with NO CONFIRM, and once the run-control family started bailing on
    # questions, every question that mentions a machine fell THROUGH to this line:
    # `what about pause the run on the shared machine` came out as `device-use`.
    # The defect pre-dates the change — `can i switch to the office PC` already
    # executed a switch at the revision this started from — but a fix that reroutes
    # traffic into an ungated branch owns that branch's gate.
    if m and (re.search(r"\b(switch to|run (it |everything )?on)\b", low) or _bare_use) \
            and not _q_start and not _runctl_dropped:
        # ⛔ A QUOTED NAME WINS OUTRIGHT — see `_quoted_name`. Everything below
        # is for the unquoted case.
        name = _quoted_name(t) or re.sub(r"[?.!,]+$", "", m.group(1)).strip()
        # ⛔ AND THE QUOTES COME OFF, as they do at unlink. The picker this client
        # prints ends every ask with 'Just say: use “<name>”.', so the one
        # phrasing the product itself teaches arrived here still wrapped.
        name = name.strip().strip(_NL_QUOTE_CHARS).strip()
        # ⛔⛤ AND THE TRAILING CLAUSE COMES OFF HERE TOO. This is the branch that
        # MUTATES WITH NO CONFIRM, and it was one of four capture sites that ran
        # the name to end-of-string: `switch to my Studio PC and show me the rest`
        # switched to a machine called “Studio PC and show me the rest”, and
        # `switch to my Studio PC please` switched to “Studio PC please”. One trim,
        # every site — the reason the helper says ONE COPY at the top.
        name = _trim_trailing_clause(name, t)
        # ⛔ A LEADING DEVICE NOUN IS NOT PART OF THE NAME. "switch to the machine
        # LABPC001" carried "machine LABPC001" into a name lookup that matches on
        # name, hostname and substring — none of which contains the word.
        name = _strip_leading_noun(name)
        if _is_bare_machine_noun(name):
            name = ""
        # ⛔⛔ THE ONE ACT BRANCH ON THIS SURFACE THAT MUTATES WITH NO CONFIRM AT
        # ALL, and it was the one I did not gate. Cross-verify found it: `switch
        # to every computer i have`, `switch to my two macs` and `run it on my
        # remaining laptops` all EXECUTED `device-use` with a set as the name.
        # `_is_bare_machine_noun` caught only `<quantifier> <bare noun>`, which is
        # why `switch to all my computers` looked safe and the rest were not.
        # ⭐ IT PRE-DATES THIS WAVE — the revision this started from does the same
        # — but it is the same question on the same surface, so it is gated here.
        # ⛔ THE PRODUCT'S OWN WORDING IS NOT A SET. This branch's capture spells
        # `run (?:it |everything )?on` verbatim, so `run everything on my Studio
        # PC` names ONE machine and the totaliser must not see the word at all.
        # The blanking is local to this branch, because on a RUN verb the same
        # word genuinely means every run.
        _sw_t = re.sub(r"\brun\s+everything\s+on\b", "run on", t, flags=re.I)
        if _request_names_a_set(_sw_t, name):
            return None, ["I run on one computer at a time. Ask me to list them "
                          "and name the one to use — nothing changes until you do."]
        return (["device-use", name] if name else ["devices"]), None
    # ⛔ `drop` IS A SYNONYM OF `remove` ON THIS SURFACE and reached the catch-all.
    # Routing it to the device LIST instead — which is where the control-word fix
    # first sent it — is not an improvement on a refusal: the person named one
    # machine and asked for something to happen to it.
    # ⛔ A BARE MACHINE TOKEN NAMES A MACHINE HERE TOO — `remove LABPC001` reached
    # the catch-all for want of the word "computer" in the sentence.
    _unlink_tok = re.search(rf"\b{_UNLINK_VERBS}\s+(?:{_NAME_DETERMINER}\s+)?"
                            rf"(\S+)\s*$", t, re.I)
    if re.search(rf"\b{_UNLINK_VERBS}\b", low) and \
            (re.search(rf"\b({_MACHINE_NOUNS_SAID})\b", low)
             or (_unlink_tok and _looks_like_a_machine_token(_unlink_tok.group(1)))):
        # ⛔ FIVE MORE DETERMINERS. The ask branch strips `the|a|an|my|their|its|
        # that|this`; this one stripped only `the|my`, so "remove that computer"
        # and "unlink their laptop" carried the word into a DESTRUCTIVE confirm.
        m = re.search(rf"\b{_UNLINK_VERBS}\s+"
                      rf"(?:{_NAME_DETERMINER}\s+)?(.+)$",
                      t, flags=re.I)
        name = re.sub(r"[?.!,]+$", "", m.group(1)).strip() if m else ""
        name = re.sub(r"^(old|other)\s+", "", name, flags=re.I)
        # ⛔ THE SAME LEADING-NOUN STRIP AS THE SWITCH BRANCH FOUR LINES UP. It
        # landed there and not here in the first pass, so "remove device LABPC001"
        # offered to unlink a machine called "device LABPC001" — a DESTRUCTIVE
        # confirm whose own follow-up cannot resolve. Cross-verify caught it.
        # ⛔ THE QUOTES COME OFF BEFORE THEY GO BACK ON. This client tells people to
        # reply with the name in quotes, so a quoted one arrives here wrapped and
        # the confirm printed ““Studio PC””.
        name = _quoted_name(t) or name.strip().strip(_NL_QUOTE_CHARS).strip()
        # ⛔⛤ THE DESTRUCTIVE CONFIRM QUOTED THE WHOLE SENTENCE. This site ran to
        # end-of-string, so `remove my Studio PC please` offered to unlink
        # “Studio PC please” and `remove my Studio PC and show me the rest`
        # offered to unlink “Studio PC and show me the rest”. A confirm whose own
        # follow-up cannot resolve is worse here than anywhere else on the
        # surface, because saying yes to it rotates an access code.
        name = _trim_trailing_clause(name, t)
        name = _strip_leading_noun(name)
        # ⛔⛔ AND NOT "that device" EITHER. The old fallback was written for a
        # message that named nothing at all; here the person DID name something,
        # it just turned out to be the noun. Confirming "Unlink that device?" and
        # then running a remove with no argument would unlink whichever one the
        # resolver happened to land on. Ask which, and remove nothing until told.
        if _request_names_a_set(t, name):
            # ⛔ UNLINK TAKES EXACTLY ONE MACHINE. Answering a bulk request with
            # "which one?" hides that the thing asked for cannot be done at all.
            # ⭐ THE CAPTURE IS PASSED SO A QUOTED NAME STILL WINS, and so
            # "remove my Studio PC, not all my macs" keeps working. Measured:
            # "remove my machines" and "remove my two macs" both reached the
            # DESTRUCTIVE confirm before this line read the plural.
            return None, ["I unlink one computer at a time. Ask me to list them and "
                          "name the one to remove — nothing is removed until you do."]
        if not name or _is_bare_machine_noun(name):
            return None, ["Which computer should I unlink? Ask me to list them and "
                          "name one — nothing is removed until you do."]
        return None, [_NL_CONFIRMS["device-remove"].format(name=f"“{name}”")]

    # 5. Session + maintenance.
    if re.search(r"\b(uninstall|tear ?down)\b", low) or \
            re.search(r"\b(remove|disconnect)\b.*\b(entirely|completely|fully|everything)\b", low):
        # ⛔ THE SAME QUESTION SKILL.md ASKS, AND IT HAS TO SAY THE SAME THING: a
        # full removal takes EVERY chat's watcher on this computer, not only the
        # one asking (owner decision, 2026-09-23 — see `_is_stream_job`). A person
        # who runs several chats off one computer must hear that before they say
        # yes, and must not hear two different answers depending on the door.
        return None, ["Just sign out, or fully remove Super Research from this "
                      "computer — the skill, the bridge and every chat’s watcher? "
                      "(Sign-out keeps everything installed.)"]
    if re.search(r"\b(sign|log)\s?(me\s)?out\b|\blogout\b", low):
        return None, [_NL_CONFIRMS["logout"]]
    if re.search(r"\b(sign|log)\s?(me\s)?in\b|\blogin\b|\bauthenticate\b", low):
        return ["login"], None
    if re.search(r"\b(i('m| am)? (signed|logged) in|i did it|signed in now)\b", low):
        return ["login-done"], None
    if re.search(r"\b(update|upgrade)\b", low):
        # "update me / any update on X / give me an update" is a PROGRESS ask,
        # not software maintenance — routing it to the update confirm made a
        # reflexive "yes" restart the backend mid-run.
        if re.search(r"\bupdates? (me|on|about|regarding|for)\b|\bany updates?\b"
                     r"|\b(give|got|have|send)\b.*\bupdates?\b|\blatest updates?\b", low):
            name = _nl_run_name(t)
            return ["status"] + ([name] if name else []), None
        # A backend-named ask that is NOT also a skill ask (e.g. "update super
        # research", "update the backend", "update the research computer") →
        # redirect: the skill doesn't update the backend (the app / the host CLI
        # does). Checked BEFORE the skill default so "update the super research
        # SKILL/agent" still self-updates the skill (the 'agent' token is still
        # accepted colloquially even though the skill no longer calls itself that).
        if not re.search(r"\b(skill|agent|bridge|chat|yourself)\b", low) and \
                re.search(r"\b(backend|super ?research|research (pc|computer|machine))\b", low):
            return None, [_NL_BACKEND_UPDATE_MOVED]
        # Everything else — "update", "upgrade", "update the skill/yourself", and
        # colloquial "update the agent" — updates the Super Research SKILL (the
        # only thing this updates now). No agent-vs-backend split → no misroute to
        # a backend that isn't on this host (the old default hit "Super Research
        # isn't installed on the connected device" for a plain "update").
        return None, [_NL_CONFIRMS["update"]]
    if re.search(r"\bversions?\b", low):
        return ["version"], None
    # ⭐⭐ "INSTALL SUPER RESEARCH" IS ANSWERED WITH THE PAGE (owner, 2026-09-24).
    # This used to send every install / set-up phrasing — "how do I install super
    # research", "set up super research" — to the confirm that installs the
    # backend on the machine the CHAT runs on, and a yes then told a brand-new
    # person to run `superresearch --pair`. What they were asking for is how to get
    # a computer, and the answer to that is the one add line with the install page
    # in it.
    # ⛔ THE CONFIRM KEEPS ONLY THE EXPLICIT ASK: "here" or "this pc / machine /
    # computer" AFTER the install verb, or the backend by name. Those are about
    # THIS machine, and that confirm now opens with the page as well.
    # ⛔⛔ TIED TO THE VERB, NOT FOUND ANYWHERE IN THE MESSAGE. The first cut took
    # `here` / `host` wherever they stood, so "I'm new here, how do I set up super
    # research" — a brand-new person, the exact reader decision 3 is for — was
    # offered the install on the machine the CHAT runs on, and so was "how do I
    # host super research for my team", which names no machine at all.
    # ⛔ AND A MESSAGE THAT NAMES THE SKILL IS NOT ASKING FOR A COMPUTER. The web
    # app's own paste-to-your-agent line is "Install Super Research from
    # superresearch.io/skills.md", and it is shown to people whose agent still has
    # this skill (`/sr logout` keeps it) — the app's tile relies on this rule to
    # keep it off the install page. It gets the fresh account check a bare /sr
    # gets: bridge and sign-in, as they stand (computers are not a login answer
    # since 2026-09-25 — a research with none says so itself).
    if re.search(r"\b(install|host|set ?up)\b.*\b(backend|super research|here|this (pc|machine|computer|device))\b", low):
        if re.search(r"\bskills?\.md\b|\b(?:skill|agent|bridge)\b", low):
            return ["status-account"], None
        if re.search(r"\b(?:install|set ?up|host)\b[^.?!,]*"
                     r"\b(?:here|this (?:pc|machine|computer|device|laptop|mac)|backend)\b",
                     low):
            return None, [_NL_CONFIRMS["install"]]
        return None, [_ADD_A_COMPUTER]

    # 6. Listing + progress (before research — "results of X" is a status ask).
    # ⛔⛤ `did they answer?` AND `any word back?` — SKILL.md teaches both as the
    #     way to check on a request you sent, and both reached the catch-all. The
    #     surface exists; nothing pointed at it.
    # ⛔⛤ `ask its owner if I can use it` IS TAUGHT AND RESOLVED NOWHERE. It names
    #     no machine — "it" is whichever row is on screen — so the honest landing
    #     is the list you pick one from, not a confident guess at which.
    # ⛔⛤ AND NOT WHEN AN ARTEFACT IS NAMED: `ask the owner for the podcast` is
    # a fetch, and this return took it.
    if (not _artefact_kw) and (re.fullmatch(
            r"(?:please\s+)?(?:can (?:i|we) )?(?:ask|request)\s+"
            r"(?:its|their|the)\s+owner\s+[^.?!]{0,48}", low)) or \
            re.fullmatch(r"(?:please\s+)?(?:can (?:i|we) )?"
                         r"(?:ask|request)\s+(?:to use|access to|for)\s+"
                         r"(?:it|this|that|one)\b[^.?!]{0,24}", low):
        return ["devices-public"], None
    if re.fullmatch(r"(?:please\s+)?(?:did (?:they|he|she|the owner) (?:answer|reply|"
                    # ⛔ A MANDATORY SPACE BEFORE AN OPTIONAL GROUP killed the
                    # bare arm: `any news` reached the catch-all while
                    # `any news yet` worked.
                    r"respond|say yes|get back to me)|any (?:word|answer|reply|news)"
                    r"(?:\s+(?:back|yet))?|have they (?:answered|replied|responded)|"
                    r"heard back(?: yet)?)", low):
        return ["device-requests"], None
    if re.search(r"\bwhat('s| is) (running|active)\b|\bactive runs?\b|\banything running\b", low):
        return ["updates"], None
    # ⛔⛤ NARROWED. `my last report` and `my recent brief` are asks about ONE
    # artefact and the status branch has always served them; `the run` and
    # `my run` likewise. I had this list eating both.
    _past_research = re.fullmatch(
        r"(?:my|the|all|our)\s+(?:past|previous|old|earlier|recent)\s+"
        r"(?:research(?:es)?|runs)|(?:my|the|our)\s+(?:researches|runs)", low)
    if re.search(r"\b(list|show|what)\b.*\b(researches|research history|past research(es)?)\b", low) or \
            low in ("list", "my researches", "researches") or _past_research:
        return ["list"], None
    # ⛔⛤ THE ARTEFACT LINKS. SKILL.md teaches `the brief link`, `a report link`,
    #     `the NotebookLM link`, `the doc` and `the video` as things to SAY, and
    #     every one reached the catch-all — the links live in the status output
    #     and nothing routed a person to it. ⛔ IT IS A FULLMATCH ON PURPOSE: the
    #     same words inside a longer sentence belong to skip (`skip the video`),
    #     to research (`research the podcast industry`) and to the branches above.
    if re.fullmatch(r"(?:please\s+|can\s+you\s+|could\s+you\s+|send\s+|show\s+"
                    r"|give\s+|get\s+)*(?:me\s+)?"
                    r"(?:the|a|an|my)\s+"
                    # ⛔⛤ `audio overview` GOES BACK TO THE PODCAST BRANCH two
                    # rules below, which is where it was and which is the only
                    # command that delivers playable audio. I took it and gave
                    # the product two spellings with two answers: bare
                    # `audio overview` fetched, `the audio overview` did not.
                    r"(?:brief|report|doc|document|google\s+doc|notebooklm|"
                    r"video|youtube|links?|results?)"
                    r"(?:\s+links?)?", low):
        name = _nl_run_name(t)
        return ["status"] + ([name] if name else []), None
    if re.search(r"\bpodcast\b|\baudio( overview)?\b", low):
        name = _nl_run_name(t)
        return ["podcast"] + ([name] if name else []), None
    if re.search(r"\bstatus\b|\bprogress\b|\bhow('s| is) (it|that|the .{1,40}) (going|coming|doing)\b"
                 r"|\bhow far\b|\bwhere('s| is) .{1,40} at\b|\bresults? (of|for)\b"
                 r"|\b(any|latest) updates?\b", low):
        name = _nl_run_name(t)
        return ["status"] + ([name] if name else []), None

    # 6b. "I HAVE NO COMPUTER." ⛔⛔ THERE WAS NO RULE FOR THIS AT ALL — measured
    #     at HEAD, "I don't have a computer of my own" (the phrasing SKILL.md gives
    #     as its own worked example) reached the catch-all, and so did "I have no
    #     computer, what can I do". The one sentence a person with nothing says was
    #     the one sentence nothing answered.
    #     ⭐ IT ANSWERS FROM THE ACCOUNT'S OWN LIST, NOT THE PUBLIC ONE. Sending
    #     these to `devices-public` tells somebody who DOES have a computer to go
    #     and ask a stranger; `devices` answers from this account's own truth and,
    #     when that is empty, IS the offer of both routes with the public ones
    #     listed.
    #     ⛔⛔ AND IT SITS HERE, DIRECTLY ABOVE THE CATCH-ALL, BECAUSE IT WAS
    #     WRITTEN AT 2e AND STOLE FIVE OTHER RULES. Cross-verify measured it:
    #     "I don't have the podcast from my computer yet" listed devices instead of
    #     fetching the podcast, "I don't have an update on my machine" lost the
    #     status ask, "I don't have time, stop the run on my mac" ate a RUN STOP,
    #     and "I don't have a computer, log me in" never reached sign-in. A
    #     negation plus a machine word appears in a great many sentences that are
    #     about something else. Down here it can only claim what nothing else did,
    #     which is exactly the population it was written for — and no guard list
    #     has to be kept in step with the rules above it.
    # ⛔ ONE GUARD SURVIVES THE MOVE, AND ONLY ONE. "I don't have the report from
    # my laptop" is about a REPORT — nothing above claims it, so being last is not
    # enough here, and answering with a device list is a wrong answer where the
    # catch-all would at least be an honest one.
    if not _artefact_kw and (re.search(
            rf"\b(?:i (?:do not|don'?t|dont) have|i have no|i haven'?t got"
            rf"|i'?ve got no|i (?:do not|don'?t|dont) own)\b[^.?!]*"
            rf"\b(?:{_MACHINE_NOUNS_SAID})\b", low)
            # ⛔⛤ AND THE BARE FORM OF THE SAME SENTENCE. SKILL.md teaches
            # "no devices — set one up" and it reached the catch-all: the
            # negation vocabulary above is all first-person, and a person
            # reporting the state does not always put themselves in it.
            or re.fullmatch(rf"(?:no|zero|0)\s+(?:{_MACHINE_NOUNS_SAID})\b"
                            rf"[^.?!]{{0,32}}", low)):
        return ["devices"], None

    # 6c. ⭐ "WHERE DO I GET AN ACCESS CODE?" HAS AN ANSWER NOW (2026-09-24). It
    #     reached the catch-all, so no reply anywhere said where a code comes from
    #     and the assistant made one up — "from the Super Research app", which is
    #     false for anybody without a computer. The add line says it: the computer
    #     shows it, at the end of the install page's setup, or its owner gives you
    #     one.
    #     ⛔⛔ IT SITS HERE, ABOVE ONLY THE CATCH-ALL, FOR 6b's REASON. Written at
    #     rule 5 it took "status of the research on where to get access codes",
    #     "results of how to get pairing codes for bluetooth" and "podcast for how
    #     to get access codes" away from status and podcast — a run TITLED with the
    #     words is not a question about the code. Down here it claims only what
    #     every rule above left.
    #     ⛔⛔ AND NEVER A RECOVERY OR A SHARING QUESTION. "I lost my access code",
    #     "how do I get a new one", "it expired", "it doesn't work", "for my friend"
    #     come from somebody whose computer ALREADY EXISTS — and the page's setup
    #     ends in the pairing step, which on a machine that still exists mints a
    #     NEW computer and drops everybody it was shared with (`_PAIR_ERRORS`). The
    #     add line would send them straight there, so those keep the catch-all
    #     they had before this rule existed. A message carrying a code never
    #     reaches here (rule 1 pairs it), and a research request that mentions
    #     codes was taken at 2b.
    if re.search(r"\b(?:access|pair(?:ing)?)[ -]?codes?\b", low) and re.search(
            r"\b(?:where|how)\b.*\b(?:get|find|obtain|receive|come|comes)\b"
            r"|\b(?:get|need|want)\s+(?:me\s+)?(?:an?|the|one)?\s*"
            r"(?:access|pair(?:ing)?)[ -]?codes?\b", low) and not re.search(
            r"\b(?:new|another|again|expired?|lost|lose|forgot(?:ten)?|reset|wrong"
            r"|right one|(?:does|do|did|is|was)\s*n[o'’]?t\s+work(?:s|ing)?"
            r"|not working|stopped working|my|mine|our|friend|wife|husband|partner"
            r"|give|share|sharing|into)\b", low):
        return None, [_ADD_A_COMPUTER]

    # 6d. ⭐ …AND THE RECOVERY AND SHARING QUESTIONS 6c TURNS AWAY GET THEIR OWN
    #     ANSWER (owner, 2026-09-24): reveal it in Account, Reset for a new one, or
    #     the screen of a computer still being set up — see `_LOST_CODE_REPLY`.
    #     The trigger is 6c's exclusion list, less "into".
    #     ⛔ NOT A QUESTION ABOUT ENTERING ONE. "How do I enter / paste / put / use my
    #     access code" is about handing a code over, which this reply does not
    #     answer — those keep the catch-all.
    #     ⛔ SAME PLACE, SAME REASON AS 6c: above only the catch-all, so a run titled
    #     with these words still reaches status, results and podcast.
    if re.search(r"\b(?:access|pair(?:ing)?)[ -]?codes?\b", low) and re.search(
            r"\b(?:new|another|again|expired?|lost|lose|forgot(?:ten)?|reset|wrong"
            r"|right one|(?:does|do|did|is|was)\s*n[o'’]?t\s+work(?:s|ing)?"
            r"|not working|stopped working|my|mine|our|friend|wife|husband|partner"
            r"|give|share|sharing)\b", low) and not re.search(
            r"\b(?:into|enter|entering|paste|pasting|type|typing|put|use|using)\b", low):
        return None, [_LOST_CODE_REPLY]

    # 7. Nothing matched — user-safe capabilities line (never guess a command).
    #    (Research phrasings were resolved at 2b, before the control rules.)
    # ⛔ THE CAPABILITY LINE IS PART OF THE SURFACE. It is what somebody reads
    # after a phrasing this resolver could not place, so a verb missing from it is
    # a verb the fallback denies having.
    return None, [_NL_CATCH_ALL]


# The only option flags _nl_resolve ever emits — everything else in a resolved
# argv is a positional. cmd_do uses this to place the `--` separator.
#
# ⛔⛔ IT WAS SHORT BY TWO, AND THAT KILLED THE WHOLE REQUEST RATHER THAN THE
# FLAG. `_nl_resolve` has emitted `--machine` and `--agent-log` since the
# send-logs routing row was written; neither was listed here, so `cmd_do`
# classified them as free text and passed them AFTER `--`. `send-logs` has no
# positional, so argparse exited 2, the SystemExit handler below caught it, and
# the person asking "send the computer's own logs to support" was answered with
# "I didn't catch a Super Research request in that." Not a dropped flag — a
# dropped request, on the one route a person reaches when something is already
# wrong. Reproduced against this parser before the fix.
#
# ⛔ EVERY FLAG HERE MUST BE A STORE_TRUE FLAG. A value-taking flag would put its
# VALUE in the positional list and behind `--`, which is the same failure one
# argument along — so `--runs` is deliberately NOT routed from natural language,
# and a guard reads this file to keep the two facts in step.
#
# ⛔ AND THE GUARD READS `_nl_resolve`'S SOURCE rather than this line, because a
# hand-kept list is exactly what fell behind. Any `"--…"` literal that function
# can append must appear here.
# ⛔⛔ `--run` CARRIES A VALUE, AND THE RELAY SPLITS ON MEMBERSHIP. `cmd_do` sorts
# every resolved token into flags-or-positionals, so a bare `--run` would land in
# flags and its value in the topic. It is emitted as ONE `--run=<name>` token and
# matched on the part before the `=`, which argparse accepts verbatim.
_DO_FLAGS = frozenset({"--no-video", "--no-email", "--machine", "--agent-log",
                       "--run"})


def cmd_do(args) -> int:
    """Resolve a verbatim user message to a command and run it (or print the
    one confirm/clarify question). The AI relays whatever this prints."""
    argv, lines = _nl_resolve(" ".join(args.text))
    if argv is None:
        return _emit({}, args.json, lines or [])
    # `--` before the free-text positionals: a topic/name that happens to start
    # with a dash ("research --help") must reach the command as a literal value,
    # never dump argparse usage into the chat relay.
    cmd, rest = argv[0], argv[1:]
    def _is_flag(a):
        return a.split("=", 1)[0] in _DO_FLAGS
    flags = [a for a in rest if _is_flag(a)]
    pos = [a for a in rest if not _is_flag(a)]
    final = (["--json"] if args.json else []) + [cmd] + flags + (["--"] + pos if pos else [])
    try:
        ns = build_parser().parse_args(final)
    except SystemExit:
        # A resolved arg the parser refused (shouldn't happen) — never crash the
        # chat turn; fall back to the ask-what-you-want line.
        return _emit({}, args.json, ["I didn’t catch a Super Research request in "
                                     "that — name a topic, a run, or a device."])
    return ns.func(ns)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sr", description="Super Research skill client")
    p.add_argument("--json", action="store_true", help="print the raw bridge JSON")
    sub = p.add_subparsers(dest="command", required=True)

    lg = sub.add_parser("login", help="start a remote sign-in")
    lg.add_argument("--runtime", default="")
    lg.add_argument("--label", default="")
    lg.set_defaults(func=cmd_login)

    sub.add_parser("login-done", aliases=["login-wait"],
                   help="poll until sign-in completes").set_defaults(func=cmd_login_wait)
    sub.add_parser("status-account", help="bridge + session status").set_defaults(func=cmd_status_account)
    sub.add_parser("devices", help="list reachable devices").set_defaults(func=cmd_devices)

    du = sub.add_parser("device-use", help="select the target device (by name or id)")
    du.add_argument("device")
    du.set_defaults(func=cmd_device_use)

    da = sub.add_parser("device-add", help="pair a device by the code on its screen")
    da.add_argument("code")
    da.set_defaults(func=cmd_device_add)

    dr = sub.add_parser("device-remove", help="unlink a device (by name or id)")
    dr.add_argument("device")
    dr.set_defaults(func=cmd_device_remove)

    sub.add_parser("devices-public",
                   help="list the computers other people offer publicly"
                   ).set_defaults(func=cmd_devices_public)

    dk = sub.add_parser("device-ask",
                        help="ask the owner of a public computer for access")
    dk.add_argument("device")
    dk.set_defaults(func=cmd_device_ask)

    sub.add_parser("device-requests",
                   help="show who is asking for your computers, and what you "
                        "are waiting on"
                   ).set_defaults(func=cmd_device_requests)

    # ⛔ THE PERSON IS OPTIONAL AND THAT IS DELIBERATE. With exactly one person
    # waiting, "approve that request" names everything it needs to; with several,
    # the command prints the queue rather than choosing one. A required argument
    # would force the router to invent a name from free text, which is the
    # mistake 7.9-2 shipped.
    dap = sub.add_parser("device-approve",
                         help="let somebody use one of your computers")
    dap.add_argument("person", nargs="?", default="")
    dap.set_defaults(func=cmd_device_approve)

    ddn = sub.add_parser("device-deny",
                         help="refuse somebody asking for one of your computers")
    ddn.add_argument("person", nargs="?", default="")
    ddn.set_defaults(func=cmd_device_deny)

    # ⛔⛔ NOT `device-public`. `devices-public` is the BROWSE list — other
    # people's machines — and two commands one letter apart, where one shows you
    # theirs and the other gives them yours, is a mistake somebody makes once and
    # cannot undo. The setting is called visibility on the machine's own terminal
    # for the same reason.
    # ⛔ THE VALUE LEADS HERE AND TRAILS IN THE TERMINAL, because the OPTIONAL
    # argument differs: chat can pick the machine when an account owns one, the
    # terminal always names it by id.
    dvi = sub.add_parser("device-visibility",
                         help="set who can find one of your computers")
    dvi.add_argument("value", choices=("public", "private"))
    dvi.add_argument("device", nargs="?", default="")
    dvi.set_defaults(func=cmd_device_visibility)

    rs = sub.add_parser("research", help="start a run")
    rs.add_argument("topic")
    rs.add_argument("--device", default="")
    rs.add_argument("--no-video", action="store_true")
    rs.add_argument("--no-email", action="store_true")
    rs.set_defaults(func=cmd_research)

    st = sub.add_parser("status", help="a run's progress (no id = most recent)")
    st.add_argument("runId", nargs="?")
    st.set_defaults(func=cmd_status)

    pod = sub.add_parser("podcast", help="a run's audio as a local file to send as native audio")
    pod.add_argument("runId", nargs="?")
    pod.set_defaults(func=cmd_podcast)

    up = sub.add_parser("updates", help="active runs + current links (streaming cron)")
    up.add_argument("--active", action="store_true")
    up.set_defaults(func=cmd_updates)

    sub.add_parser("list", aliases=["researches"],
                   help="list ALL recent researches (any status) to pick one by name") \
        .set_defaults(func=cmd_list)

    # Graceful stop (keeps results + chat). `cancel` is an alias for the same
    # graceful behavior so an old habit never triggers a destructive delete.
    for _name, _help in (("stop", "gracefully stop a run (no run = most recent active)"),
                         ("cancel", "alias for stop (graceful — keeps results + chat)")):
        sp = sub.add_parser(_name, help=_help)
        sp.add_argument("runId", nargs="?")
        sp.set_defaults(func=cmd_stop)

    pa = sub.add_parser("pause", help="pause a running run (stays resumable)")
    pa.add_argument("runId", nargs="?")
    pa.set_defaults(func=cmd_pause)

    rsm = sub.add_parser("resume", help="resume a paused run")
    rsm.add_argument("runId", nargs="?")
    rsm.set_defaults(func=cmd_resume)

    rt = sub.add_parser("retry", help="resume a run waiting on a decision / error")
    rt.add_argument("runId", nargs="?")
    rt.set_defaults(func=cmd_retry)

    # No args → skip whatever the run is blocked on; phases → trim those
    # phases; agent names (chatgpt/gemini/claude) → turn those P2 agents off.
    sk = sub.add_parser("skip", help="skip a run's current blocker, named phases, or P2 agents")
    sk.add_argument("phases", nargs="*")
    sk.add_argument("--run", default="", help="run title or id (default: newest active run)")
    sk.set_defaults(func=cmd_skip)

    # Confirm-first: the bare form SHOWS what would be sent and sends nothing.
    sl = sub.add_parser("send-logs", aliases=["logs", "send-log"],
                        help="send Super Research support the logs from the connected computer")
    sl.add_argument("--confirm", action="store_true",
                    help="actually send (the bare command only shows what would go)")
    sl.add_argument("--machine", action="store_true",
                    help="also send that computer's own logs (its owner only)")
    sl.add_argument("--agent-log", dest="agent_log", action="store_true",
                    help="also send the log from the agent on this host")
    sl.add_argument("--runs", default="",
                    help="which runs, by the numbers shown or by name, "
                         "comma-separated; 0 is the agent's own log on this host "
                         "and all is every run listed (default: every run listed)")
    sl.add_argument("--none", action="store_true",
                    help="send no runs — for connection problems, with --machine")
    sl.add_argument("--device", default="", help="which computer (name or id)")
    sl.add_argument("--status", default="", metavar="CODE",
                    help="report on a support code instead of sending")
    sl.set_defaults(func=cmd_send_logs)

    sub.add_parser("logout", help="clear the account session").set_defaults(func=cmd_logout)

    sub.add_parser("version", aliases=["versions"],
                   help="show the Super Research skill version (+ update notice)").set_defaults(func=cmd_version)
    sub.add_parser("install", aliases=["install-backend", "setup-backend"],
                   help="install the Super Research backend on the connected device (host a BE)"
                   ).set_defaults(func=cmd_install)
    # `update` updates the Super Research SKILL (this chat runtime — /sr scripts +
    # bridge), the ONLY thing the runtime updates. Backend updates are done in the
    # app / with `superresearch --update` on the host — there is no backend-update
    # subcommand here. `install` (host a backend) is unaffected. NL ("upgrade",
    # "update the skill", etc.) resolves through `do`, so `update-skill` is the
    # only alias kept.
    sub.add_parser("update", aliases=["update-skill"],
                   help="update the Super Research skill (this chat — scripts + bridge) to the latest"
                   ).set_defaults(func=cmd_update)

    sub.add_parser(
        "arm-stream",
        help="prepare this chat's streaming watchdog (prints the cron script + name to arm)",
    ).set_defaults(func=cmd_arm_stream)

    do = sub.add_parser("do", aliases=["nl"],
                        help="resolve a verbatim user message to a command and run it")
    # REMAINDER: capture the whole message even when a token starts with "-"
    # ("do research --help") — the message is data, never options of `do`.
    do.add_argument("text", nargs=argparse.REMAINDER)
    do.set_defaults(func=cmd_do)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    # ⛔⛔ --json DISCARDS EVERY RENDERED LINE (see `_emit`), so the empty state's
    # second look was 20 seconds of wall clock spent to build a string nobody
    # reads — on the STREAMING CRON's own invocation, which runs every minute.
    # Measured by cross-verify. The flag is read where the look is made.
    global _RENDERING_LINES
    _RENDERING_LINES = not getattr(args, "json", False)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
