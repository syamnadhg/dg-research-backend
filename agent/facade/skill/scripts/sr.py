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
  login              start a remote sign-in → prints a code + link to relay
  login-done         poll until the sign-in is approved / expires (alias: login-wait)
  status-account     is the bridge up + signed in?
  devices            list reachable devices
  device-use <name>  choose the device runs go to (name or id)
  device-add <code>  pair a new device by the code on its screen
  device-remove <name>  unlink a device (owner keeps it re-pairable; sharer leaves)
  research <topic>   start a run (--device <id> to override the selected device)
  status [run]       a run's progress + links + any blocker (no run = most recent)
  podcast [run]      download a run's audio → a local file to send as native audio
  updates            active runs + their links + any that need you (streaming cron)
  stop [run]         gracefully stop a run, keeping the results so far + the chat
  retry [run]        resume a run that's waiting on a decision / hit an error
  skip [phases…]     skip the run's current blocker (no phases) or named phases
                       (--run <run> to target one; else the latest active run)
  arm-stream         prepare this chat's streaming watchdog → prints the cron
                       script + job name to arm via the runtime's cronjob tool
  version            show the Super Research skill version
  update             update the Super Research skill (this chat — scripts + bridge)
  logout             clear the account session
  help               this list

Add --json to print the raw bridge response (the streaming cron uses
`sr.py --json updates`).
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
_SKILL_BUILD = "0.1.32"

_TIMEOUT = 30
# By-title run resolution scans the newest N runs (status / podcast / list / the
# resume verbs). 20 was too shallow — a run a few weeks back (named, not active)
# fell outside the window, so `podcast "Rocky Port…"` silently found nothing and
# the agent improvised. 100 covers a deep history; it's a plain Firestore list
# (no per-phase minting — that's only the via=agent `updates` path, left at 20).
# Mirrors the bridge's /updates limit cap (bridge.py `_updates`).
_LOOKUP_LIMIT = 100

# The human setup page (full walkthrough + the pro-account note). A markdown
# hyperlink so it lands as a clickable label in chat, not a bare URL. Kept
# distinct from the install.ps1/.sh SCRIPT URLs below.
_INSTALL_PAGE_URL = "https://superresearch.io/install"
# Bare URL (auto-links on every channel — NO Markdown, which would hard-code a
# rich-text channel assumption). Conditional lead ("don't have one?") so it reads
# gracefully even where the caller already told a user WITH a backend to just
# paste their pair code (reason=no_devices = no *paired* device, which includes an
# installed-but-unpaired machine — that user pairs, they don't reinstall).
_INSTALL_PAGE_LINE = (
    f"Don't have your own Research Computer yet? Set one up — full walkthrough: {_INSTALL_PAGE_URL}"
)

# How to install Super Research on a fresh Research Computer (no backend yet):
# the SAME one-line installer the web app's "Set up your own Research Computer"
# tile uses (auto-installs Python + pipx + superresearch), then `--pair`. Kept in
# ONE place so the `devices`-empty and `research`-no-device prompts stay identical
# + in sync with the web app. (Older builds said `pipx install superresearch`.)
_SETUP_NODE_LINES = [
    _INSTALL_PAGE_LINE,
    "It runs the research on a machine of yours (your PC / Mac / Linux box).",
    "",
    "Quick start — run one line there (pick your OS):",
    # Indent (not ``` fences) so the commands stay readable on plain-text
    # channels too — an SMS/relay that can't render Markdown would otherwise show
    # literal backticks. Matches sr_attention_poll._signed_in_line's 6-space style.
    "      irm https://superresearch.io/install.ps1 | iex      # Windows",
    "      curl -fsSL https://superresearch.io/install.sh | sh  # macOS / Linux",
    "      superresearch --pair",
    "It installs Super Research and prints an 8-char access code — read it to me.",
]

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
_PUBLIC_ASK_INVITE = ("Tell me which one to ask for — its name, or the id beside it "
                      "if two read the same. Its owner decides, and they see your "
                      "name — or your email, if you haven’t set one.")

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
            return [f"Or ask to use somebody else’s — {said[0].lower()}{said[1:]}"]
        return ["Or ask to use somebody else’s — say “show me public computers” "
                "and I’ll look again."]
    rows = [d for d in (body.get("devices") or []) if isinstance(d, dict)]
    if not rows:
        # ⛔⛔ THE THIRD THING IS STILL SAID WHEN THERE ARE NONE. "Nobody is
        # offering one" on its own answers a question this reader did not ask and
        # silently drops the option — they are left with the pair code again, which
        # is the dead end this whole block exists to remove. The option is named,
        # then the truth about today.
        # ⛔ AND THE SHARED SENTENCE KEEPS ITS OWN LINE. Splicing it after an
        # em-dash printed "— A computer shows up there…" with a capital A
        # mid-sentence; it is written as a sentence because the browse screen uses
        # it as one.
        lines = ["Or ask to use somebody else’s — but nobody is offering one "
                 "publicly right now.",
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
        lines = ["Or ask to use somebody else’s — but every computer on offer is "
                 "already shared with as many people as it can hold:"]
    else:
        lines = ["Or ask to use somebody else’s — these are on offer right now:"]
    lines += [_public_row_line(d) for d in rows]
    if body.get("truncated"):
        lines.append(_PUBLIC_TRUNCATED_SOME)
    lines.append(_PUBLIC_ASK_INVITE)
    return lines


def _no_device_lines(lead: str | None = None) -> list[str]:
    """THE empty state. Every screen that tells somebody this account has no
    research computer renders it through here.

    ⛔⛔ TEN SENTENCES USED TO SAY THIS AND THEY ALL SAID SOMETHING DIFFERENT —
    the list command, the status line, a name that would not resolve, a run that
    could not be routed, the sign-in announce, the picker's own fallback, the
    watcher, and the terminal. Every one of them offered exactly ONE way out:
    paste a pair code. Somebody with no machine of their own, and no way to get
    one, was told to go and get one.

    ⭐ THREE THINGS, IN THIS ORDER, EVERY TIME. There is no computer on this
    account · your own can be added with a pair code · or you can ask to use
    somebody else's — and the ones on offer are LISTED, because "ask for a public
    one" with no list is advice rather than a next step.

    ⛔ `lead` is for the callers that arrive with an object already in hand (a
    topic that has nowhere to run). It is NOT a second phrasing of the three
    things — it names what was being attempted, and the three things follow it
    unchanged.
    """
    lines = [lead] if lead else []
    lines.append("No research computer on this account yet.")
    lines.append("Add your own: paste the access code from the computer running "
                 "Super Research and I’ll connect it.")
    lines += _public_offer_lines()
    lines.append("")
    lines += _SETUP_NODE_LINES
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


def _post(path: str, body: dict | None = None) -> tuple[int, dict]:
    return _request("POST", path, body if body is not None else {})


def _emit(payload: dict, as_json: bool, lines: list[str], code: int = 0) -> int:
    """Print either the raw JSON (cron) or the friendly lines (chat relay).

    Returns the process exit code so the streaming cron can tell success (0)
    from a bridge/session failure (non-zero)."""
    if as_json:
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


_SR_LINK_LABELS = {
    "brief": "Brief", "chatgpt": "ChatGPT report", "gemini": "Gemini report",
    "claude": "Claude report", "podcast": "Podcast",
}


def _fmt_sr_links(sr_links: dict) -> list[str]:
    """The permanent Super Research share links (the ones in the delivered doc —
    they never expire or get revoked). These are what to hand out when the user
    asks for "the podcast link" / a doc link."""
    if not sr_links:
        return []
    out = ["  Permanent links (never expire — safe to share):"]
    for key in ("podcast", "brief", "chatgpt", "gemini", "claude"):
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
    SR permanent links (🔒: Brief + the agent reports + the Podcast) AND the real
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
        return None, _no_device_lines()
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


def _scripts_dir() -> Path:
    """The HERMES_HOME/scripts dir where the watchdog + its shims live (the
    cronjob tool requires scripts there). Derived from this file's install
    location (<HERMES_HOME>/skills/research/sr/scripts/sr.py → <HERMES_HOME>/
    scripts) so a shim lands beside sr_attention_poll.py and can import it.

    The derivation is AUTHORITATIVE for the deployed Hermes layout REGARDLESS of
    whether the watchdog copy has landed yet: if it hasn't, _write_poll_shim then
    surfaces a clean "re-run agent connect" error — rather than this silently
    returning the skill BUNDLE's own scripts dir (which also holds a watchdog copy
    but is a path the cron tool rejects, masking the real failure with a confusing
    cron error). $HERMES_HOME and a local dir only cover a non-standard layout the
    derivation can't recognize."""
    here = Path(__file__).resolve()
    if len(here.parents) >= 5 and here.parents[1].name == "sr":
        return here.parents[4] / "scripts"  # deployed Hermes layout (authoritative)
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env) / "scripts"
    return here.parent  # unrecognized layout — best effort


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
    grace window and fires on the very next tick; ``repeat.times=None`` = forever,
    so mark_job_run never auto-removes it."""
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
        "next_run_at": now,
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
    RUNNABLE job of this name is left untouched, and a disabled/paused one is revived
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
        if existing is not None:
            # Present — but "present" only counts as ARMED if it can actually run. A
            # disabled/paused row is skipped by the runtime's due-scan before any
            # next-run recovery, so treating it as armed would leave the chat silent
            # with no way back (a re-arm would keep finding it). Revive it in place
            # instead of appending a duplicate (duplicates break name lookups).
            if existing.get("enabled", True) and existing.get("state") != "paused":
                return True  # genuinely armed — idempotent no-op
            existing.update({"enabled": True, "state": "scheduled", "paused_at": None,
                             "paused_reason": None,
                             "next_run_at": _cron_now()})  # due now, inside the grace window
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


# INTERVAL, deliberately — not a cron expression. Both persist identically (the
# runtime stores whatever we write and re-reads it each tick), but a cron-expr
# schedule needs the runtime's OPTIONAL croniter dependency: without it, next-run
# computation returns None, so the job would fire ONCE and then go permanently
# silent — the exact failure this fix exists to eliminate, in an unrecoverable form
# (a re-arm is idempotent, so it would find the broken row and leave it). An
# interval schedule never touches croniter, so it ticks forever either way.
_STREAM_SCHEDULE = {"kind": "interval", "minutes": 1, "display": "every 1m"}
_UPDATE_NOTICE_SCHEDULE = {"kind": "interval", "minutes": 1440, "display": "every 1440m"}


# ── commands ────────────────────────────────────────────────────────────────

def cmd_login(args) -> int:
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

    Returns {} on any failure: a courtesy line is never worth failing a sign-in over.
    """
    q = "/updates?via=agent&limit=1"
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


def cmd_login_wait(args) -> int:
    code, body = _post("/login/remote/poll")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    state = body.get("state")
    if state == "connected":
        who = body.get("email") or body.get("uid")
        topic = (body.get("pendingTopic") or "").strip()
        # ⭐ SAY WHAT HAPPENED, IN THE NOTE'S OWN WORDS, rather than a guess assembled
        # from the poll reply. The note knows the four outcomes the poll reply cannot:
        # the bridge started it, there is nowhere to run it, several computers could
        # and none is obvious, or a topic is simply waiting. Taking it is also what
        # stops the watchdog repeating this in a minute — which is what SKILL.md has
        # always told the assistant this command does.
        #
        # ⛔ BUT ONLY WHEN THE NOTE ACTUALLY CARRIES NEWS. `_signed_in_lines` returns
        # exactly ONE line for a plain sign-in and more for each of the four outcomes,
        # so `> 1` is precisely "it knows something this reply does not". Preferring
        # the note unconditionally would have been a quiet regression: for a plain
        # sign-in `_connected_msg` is DEVICE-AWARE and steers an account with no
        # computer to pair one, and the note's single line cannot. Taking it still
        # stops the double announce either way — that is the half that matters.
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
        note = _claim_signed_in_announce()
        if isinstance(note, dict) and (note.get("autoStarted")
                                       or note.get("needsDevice")
                                       or note.get("needsDeviceChoice")):
            # A bridge-decided outcome: relay it in the note's own words. `body` still
            # rides along so `--json` keeps every field the note carried.
            return _emit({**body, "signedIn": note}, args.json, _signed_in_lines(note))
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
            # `research "<topic>"`, which starts it (or surfaces the pair-a-device
            # prompt if there's no device). Don't also print _connected_msg's
            # no-device prompt here — running the research handles that once.
            return _emit(body, args.json, [
                f"✓ Connected as {who}.",
                f"Continuing your research on “{topic}”…",
            ])
        return _emit(body, args.json, [_connected_msg(who)])
    msg = {
        "pending": "… not approved yet — approve it in your browser; you'll connect automatically.",
        "expired": "✗ The sign-in link expired — ask me to send a fresh sign-in link.",
        "error": f"✗ Sign-in failed: {body.get('error', 'unknown')}",
    }.get(state, f"state: {state}")
    return _emit(body, args.json, [msg])


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


def _has_device() -> bool:
    """Does the signed-in account have at least one usable device? A device is the
    prerequisite to run research. On a transient /devices error, assume YES so we
    never wrongly nag a paired user to pair again."""
    try:
        code, body = _get("/devices")
        if code == 200:
            return bool((body or {}).get("devices"))
    except Exception:
        pass
    return True


def _connected_msg(who) -> str:
    """Post-sign-in confirmation, device-aware: steer a deviceless account to connect
    one (research can't run without a device) instead of saying 'fire your research'.
    Natural language only — no command syntax (the user just talks to the assistant)."""
    if _has_device():
        return f"✓ Connected as {who} — you’re all set."
    # ⛔ ONE LINE, AND IT STILL CARRIES BOTH WAYS OUT. This is a confirmation, not
    # the empty state — it must not fire a second fetch to render a list — but the
    # sentence that used to end at the pair code was the first thing a brand-new
    # account read, and it named the one route that needs hardware.
    return (f"✓ Connected as {who}. To get started, paste the access code from your "
            "Research Computer — or ask me for a public computer you could use.")


def cmd_status_account(args) -> int:
    code, body = _get("/status")
    if code != 200:
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))
    if body.get("authed"):
        lines = [f"✓ Signed in as {body.get('email') or body.get('uid')}"]
        if not _has_device():
            lines += _no_device_lines()
    elif body.get("remoteLogin") == "pending":
        # A sign-in is mid-flight: approve it in the browser and the bridge
        # captures it automatically (no second command needed) — #848.
        lines = ["A sign-in is in progress — approve it in your browser; you'll connect automatically."]
    elif body.get("remoteLogin") in ("error", "expired"):
        lines = ["The last sign-in didn't complete — just ask me to log you in again."]
    else:
        lines = ["Not signed in — tell me to log you in and I'll send a link."]
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
        return _emit(body, args.json, _no_device_lines())
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
            state = ", public" if d.get("visibility") == "public" else ", private"
        lines.append(f"  {mark} {_dev_label(d)}  ({kind}{state})")
    if not selected:
        lines.append("Tell me which one you’d like to use.")
    lines.append("You can add, remove, or switch devices anytime — just ask.")
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


# Friendly wording for the web app's claim/unpair error codes.
_PAIR_ERRORS = {
    "invalid_code_format": "Pair codes are 8 letters/digits (like K7XQ-9B2M) — check the device's screen.",
    "code_not_found": "That code didn’t match any device — re-check it on the device’s screen.",
    "code_expired": "That code expired — reset the pair code on the device and try the fresh one.",
    "not_previous_owner": "That device is waiting for its previous owner to re-pair — only they can.",
    "revoked_sharer": "The owner removed your access to that device — ask them to share it again.",
    "share_cap_reached": "That device has reached its sharer limit.",
    "rate_limited": "Too many attempts — wait a few minutes and try again.",
}


def cmd_device_add(args) -> int:
    """Pair a device to this account by the code shown on its screen."""
    code, body = _post("/device/pair", {"code": args.code})
    if code != 200:
        err = body.get("error", "")
        msg = _PAIR_ERRORS.get(err, f"couldn’t add the device: {err or code}")
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
    lines.append("You can add, remove, or switch devices anytime — just ask.")
    return _emit(body, args.json, lines)


def cmd_device_remove(args) -> int:
    """Unlink a device (owner: device stays installed + re-pairable; sharer: leaves it)."""
    dev, fail = _resolve_device_arg(args.device)
    if dev is None:
        return _emit({}, args.json, fail, 1)
    code, body = _post("/device/remove", {"deviceId": dev.get("id")})
    if code != 200:
        err = body.get("error", "")
        msg = _PAIR_ERRORS.get(err, f"couldn’t remove the device: {err or code}")
        return _emit(body, args.json, [f"✗ {msg}"], _fail_code(code))
    label = _dev_label(dev)
    if body.get("action") == "left-shared":
        return _emit(body, args.json, [f"✓ Left the shared device “{label}”."])
    return _emit(body, args.json, [
        f"✓ Unlinked “{label}” from your account.",
        "(Nothing was deleted — the device keeps running and can be re-paired with its code.)",
    ])


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

    ⛔ THE WAIT IS THE SERVER'S NUMBER OR NOTHING. This is the first refusal in
    the product where the reply carries `retryAfterMs`; every other one omits a
    duration precisely because no client could know it, and inventing one here
    beside a number that was handed over would be the worse half of both habits.
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


def _public_row_line(d: dict) -> str:
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
    # ⛔⛔ THE ID IS PRINTED AND IT IS NOT DECORATION. Public labels collide —
    # every unnamed machine is the identical string "Research computer" — and
    # the list is ordered online-first over a thirty-second window, so neither
    # a name nor a position identifies a row for long. The ask takes the id.
    return f"  • {label}{dot}{full}  (id {d.get('deviceId')})"


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
    lines = [f"Public computers ({len(rows)}):"]
    lines += [_public_row_line(d) for d in rows]
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
    code, body = _post("/device/ask", {"deviceId": device_id})
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
        "You removed this person from that computer before. Resetting its pair "
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
        "depends on their own notification settings. Giving them the pair code "
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
                 "Nobody can find it. A pair code still lets someone in without "
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
    """
    w = (wanted or "").strip()
    if " " in w or len(w) < 8:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*[-_][A-Za-z0-9_-]*[A-Za-z0-9]", w))


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
                     "the same as somebody you gave a pair code to. Saying no "
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
    if reason == "stale_selection":
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
    """
    if not isinstance(note, dict) or not note:
        return []
    who = str(note.get("email") or "").strip()
    topic = str(note.get("topic") or note.get("pendingTopic") or "").strip()
    quoted = f"“{topic}”" if topic else "your research"
    head = f"✓ Signed in{(' as ' + who) if who else ''}."
    if note.get("autoStarted"):
        where = str(note.get("deviceName") or "").strip()
        # ⛔ "STARTED ON MACBOOK" READS AS WORK IN PROGRESS. Auto-start routes to a
        # persisted selection or a sole computer without consulting power — right,
        # because a sleeping computer takes the work when it wakes — so "started"
        # can mean "queued until somebody switches it on", which could be tomorrow.
        # ⚠ Only an explicit False says so: an absent flag means we do not know,
        # and inventing a wait would be its own falsehood.
        if where and note.get("deviceOnline") is False:
            return [head, f"🚀 {quoted} is queued on {where} — it's switched off, "
                          f"so it starts when it comes on."]
        return [head, f"🚀 Started {quoted}{(' on ' + where) if where else ''}."]
    if note.get("needsDevice"):
        return [head] + _no_device_lines(lead=f"{quoted} has nowhere to run yet.")
    if note.get("needsDeviceChoice"):
        return [head] + _pick_device_lines(
            {"devices": note.get("devices")},
            "stale_selection" if note.get("staleSelection") else "no_selection",
            about=quoted)
    if topic:
        return [head, f"Continue with {quoted}? Say go ahead and I'll start it."]
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
        if not reason:
            reason = ("no_devices" if ("no devices yet" in err or "grab the pair code" in err)
                      else ("no_selection" if "no device" in err else ""))
        if reason == "no_devices":
            return _emit(body, args.json, _no_device_lines(), _fail_code(code))
        if reason in ("no_selection", "stale_selection"):
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
    return _emit(body, args.json, lines + _stream_health_lines(runs))


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
            return _emit(body, args.json, [
                f"Nothing has come back for {want} yet. That computer may still "
                "be packaging it, or may not have picked the request up."])
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

    path = "/logs/runs"
    device_arg = getattr(args, "device", "") or ""
    if device_arg:
        dev, fail = _resolve_device_arg(device_arg)
        if dev is None:
            return _emit({}, args.json, fail, 1)
        path += f"?deviceId={dev.get('id')}"
    code, body = _get(path)
    if code != 200:
        if body.get("reason") in ("no_selection", "stale_selection", "no_devices"):
            return _emit(body, args.json,
                         _pick_device_lines(body, body.get("reason", "")), _fail_code(code))
        return _emit(body, args.json, [f"✗ {body.get('error', code)}"], _fail_code(code))

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
        return _emit(body, args.json, [
            f"“{name}”’s own logs belong to whoever owns it, so I can’t include "
            "them. Ask again without them and you’ll still get every run of "
            "yours it’s holding."], 1)

    names = [r.get("name") for r in rows]
    if getattr(args, "runs", ""):
        chosen, picked_agent_log, refusal = _resolve_log_selection(rows, args.runs)
        if refusal:
            return _emit(body, args.json, refusal, 1)
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
        # ⛔⛔ THE AGENT'S LOG CANNOT STAND ALONE. It is uploaded into the folder
        # the machine's bundle row names — the app's Clear-logs finds objects by
        # listing that folder and nothing else — so with no bundle there is
        # nowhere it could go that a person could later delete. Without this the
        # two sentences below would tell somebody who picked only 0 that there is
        # nothing to send, about the one thing they did pick.
        if agent_log:
            return _emit(body, args.json, [
                "The agent’s own log can only go up beside a bundle from that "
                "computer, so something has to be in that bundle. Pick a run as "
                "well — or, if you own it and the trouble is reaching it at all, "
                "ask for the computer’s own logs too."], 1)
        if not body.get("published"):
            # ⛔⛔ NOT "it isn't holding any of your runs". The list is absent,
            # which means we cannot see it — a computer that hasn't published
            # one yet, or one on an older build. The other sentence tells
            # somebody their logs are gone while that machine may hold them all.
            return _emit(body, args.json, [
                f"“{name}” hasn’t told me which runs it’s still holding, so I "
                "can’t offer you a list yet."] + ([
                    "If you own it, I can still send the computer’s own logs — "
                    "that’s the right choice when the problem is with connecting "
                    "it at all."] if owned else []), 1)
        return _emit(body, args.json, [
            f"“{name}” isn’t holding logs for any of your runs."] + ([
                "If the problem is with connecting it at all, I can send the "
                "computer’s own logs instead — just ask."] if owned else []), 1)

    total = sum(int(r.get("sizeBytes") or 0) for r in rows if r.get("name") in names)

    if not getattr(args, "confirm", False):
        lines = [f"I can send Super Research support the logs from “{name}”:"]
        # ⛔⛔ EVERY ROW, NUMBERED, AND MARKED GOING OR NOT — not only the ones
        # going. Before this the plan listed the selection and nothing else, which
        # was honest while the selection was always everything; the moment a
        # subset became expressible, a list of only what is going stopped being a
        # list somebody could pick FROM. The numbers are the whole point: they are
        # what a person says back, and a run that is not on screen cannot be asked
        # for. What is going is still unambiguous — the marker carries it, and the
        # count below repeats it in words.
        for i, row in enumerate(rows, 1):
            going = row.get("name") in names
            lines.append(f"  {i} {'•' if going else '·'} {_log_run_label(row)} — "
                         f"{_size_words(row.get('sizeBytes'))}"
                         f"{'' if going else '   (not picked)'}")
        if body.get("truncated"):
            lines.append("  (only the most recent are listed — it’s holding more)")
        # ⛔ THE 0 ROW PRINTS EITHER WAY, so the choice exists for somebody who
        # does not already know it does. `--agent-log` shipped in 2026-08-26 and
        # has been reachable only by naming it.
        # ⛔ "MAY NOT BE", NOT "IS NOT" — the terminal's twin. The recommended
        # install co-locates the agent and the backend, so asserting the two
        # differ is false for most people reading it.
        lines.append(f"  0 {'•' if agent_log else '·'} the log from the agent on "
                     "THIS host — the machine running this chat, which may not "
                     "be that computer"
                     f"{'' if agent_log else '   (not picked)'}")
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
            # ⛔⛔ WHOSE, NOT ONLY WHAT — the twin of the terminal's line, and the
            # machine-log sentence three lines above already names the people its
            # material covers while this one named nobody. A second person who
            # signed in on this host is in that file, and nothing gates the upload
            # on who owns the host, because an agent host has no owner to ask.
            lines.append("It covers everyone who signed in through this agent "
                         "since that file last rotated, not only you — there’s no "
                         "owner to ask on a machine like that, so nothing checks.")
            # ⛔⛔ NAMED, because "not research content" is what it is NOT.
            # Measured in the file the uploader reads.
            lines.append("Among what’s in it: a masked form of your email "
                         "address, the ids of the computers and runs this agent "
                         "has touched, file paths on that machine, and — when a "
                         "lookup fails — your account id.")
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
        ]
        return _emit({**body, "wouldSend": names, "includeMachine": machine},
                     args.json, [*lines, *_agent_directive_block(directives)])

    payload = {"runNames": names, "includeMachine": machine,
               # ⛔ Set on this branch ONLY. It claims the person was shown what
               # leaves their computer, and the branch above is where that
               # happened. Moving it up would make the claim false.
               "consent": True,
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
    if agent_log:
        # ⛔⛔ THE AGENT'S LOG CANNOT GO YET, AND THIS SAYS SO RATHER THAN SILENTLY
        # DROPPING IT. It may only be uploaded once the machine's row has landed —
        # the app's Clear-logs finds objects by listing each ROW's folder, so
        # anything written before the row exists is a readable log the privacy
        # button can never reach. This client does not wait for anything, so the
        # second step is handed to the assistant as a directive rather than
        # attempted here and failed.
        lines.append("The agent’s own log goes up once that computer’s bundle "
                     "lands — ask me to check on it and I’ll finish that part.")
        directives.append(
            f"Once the bundle shows done, run: sr send-logs --status {support} "
            "--agent-log   (it is refused until then, by design)")
    return _emit(sent, args.json, [*lines, *_agent_directive_block(directives)])


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
    for p in args.phases:
        lp = p.lower()
        if p.isdigit():
            phases.append(int(p))
        elif lp in _SKIP_NAMES:
            phases.append(_SKIP_NAMES[lp])
        elif lp in _SKIP_AGENTS:
            agents.append(_SKIP_AGENTS[lp])
        else:
            return _emit({}, args.json,
                         [f"✗ unknown phase '{p}' (1/3/4/5, brief/podcast/video/report, "
                          f"or a Research agent: chatgpt/gemini/claude)"], 1)
    payload: dict = {}
    if phases:
        payload["phases"] = phases
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
    background; pairing afterwards is done on the host."""
    code, body = _post("/install-backend")
    if code != 200:
        err = body.get("error", "")
        if err == "install_helper_failed":
            msg = "couldn't start the install (is pipx available on the connected device?)"
        else:
            msg = f"couldn't start the install: {err or code}"
        return _emit(body, args.json, [f"✗ {msg}"], _fail_code(code))
    if body.get("already"):
        return _emit(body, args.json, [
            "Super Research is already installed on this device.",
            "To update it, run “superresearch --update” on that computer or update "
            "it from the app (Settings → About); say “devices” to see/pair it.",
        ])
    return _emit(body, args.json, [
        "⬇️ Installing Super Research on this device in the background.",
        "When it finishes, pair it — run this on that PC:",
        # Indent (not ``` fences) — plain-text/SMS relays can't render Markdown
        # and would show literal backticks. Matches _SETUP_NODE_LINES' style.
        "      superresearch --pair",
        "It shows an 8-char code; read it to me and I’ll add it.",
        "(Then finish the API-key + browser-login steps on the PC and it’s ready.)",
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
    armed = _arm_stream_cron(script_name, job_name, origin, _STREAM_SCHEDULE)
    # The once-daily update notice rides the same deterministic arm (best-effort: its
    # result doesn't gate the fallback below — only the watchdog's does, since a missed
    # update NOTICE is cosmetic while a missed watchdog is the bug we're fixing).
    _arm_stream_cron("sr_update_notice.py", "sr-update-notice", origin,
                     _UPDATE_NOTICE_SCHEDULE)
    payload = {"script": script_name, "name": job_name,
               "schedule": _STREAM_SCHEDULE["display"],
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
# The research-verb pattern, anchored at message start. Checked EARLY (before
# the control/status rules) so a research request whose TOPIC contains words
# like stop/pause/status/podcast ("research how to stop smoking") can never be
# hijacked into a run-control or status command.
_NL_RESEARCH_RE = re.compile(
    r"^(?:please |can you |could you |would you |hey |ok |okay |go |now )*"
    r"(?:(?:do|run|start|fire|kick ?off|launch|begin) (?:a |another |the )?)?"
    r"(?:super ?research|deep[- ]?research|deep[- ]?dive|research|look into|"
    r"investigate|dig into|analy[sz]e)\b(?: on| into| about| for| of)?\s*(.*)$",
    re.I)
# Words that mean "the current run", not a run name — drop, don't pass as title.
_NL_GENERIC_RUN = {"it", "that", "this", "them", "run", "the run", "this run",
                   "that run", "the current run", "current run", "the research",
                   "research", "the last one", "everything",
                   # the product's own name is never a run title
                   "super", "super research", "the super research"}
_NL_PHASE_WORDS = ("brief", "podcast", "video", "report", "email")
# P2 agent nouns for skip asks ("skip Claude in P2"). Ordered longest-first so
# "chatgpt" wins its substring "gpt" when rendering back into skip args.
_NL_AGENT_WORDS = ("chatgpt", "claude", "gemini", "gpt")
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
    """Drop a leading category word — but never the first word of a NAME."""
    m = re.match(rf"^(?:{_UNAMBIGUOUS_NOUNS})\s+(.+)$", (name or "").strip(), re.I)
    if m:
        return m.group(1).strip()
    m = re.match(rf"^(?:{_NAMEABLE_NOUNS})\s+(.+)$", (name or "").strip(), re.I)
    if m and _looks_like_an_identifier(m.group(1).strip()):
        return m.group(1).strip()
    return (name or "").strip()


def _is_bulk_machine_phrase(name: str) -> bool:
    """"all my devices", "every computer" — a request naming no single machine."""
    return bool(re.fullmatch(
        rf"(?:all|every|each|both)\s+(?:my\s+|the\s+|of\s+my\s+)?"
        rf"(?:{_MACHINE_NOUNS}|phones?)", (name or "").strip(), re.I))


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
        rf"(?:{_MACHINE_NOUNS}|phones?)", (name or "").strip(), re.I))

_NL_QUOTE_CHARS = "“”‘’\"'"

_NL_CONFIRMS = {
    "stop": "Stop {name}? It ends the run — everything finished so far is kept. Say yes and I’ll stop it.",
    "logout": "Sign out of Super Research? (The skill stays installed — you can sign back in anytime.) Say yes and I’ll sign you out.",
    "device-remove": "Unlink {name}? Nothing gets deleted — an owner’s device can re-pair with its code. Say yes and I’ll remove it.",
    "update": "Update the Super Research skill (this chat runtime)? The bridge restarts briefly. Say yes and I’ll update it.",
    "install": "Install the Super Research backend on the connected device? Say yes and I’ll set it up.",
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
                      "on that computer — the same as somebody you gave a pair "
                      "code to. Say yes and I’ll tell them yes.",
    # ⛔⛝ DENYING CONFIRMS TOO, AND ITS COST IS THE ONE NOBODY IS TOLD. A refusal
    # stops that person asking again for a week; the app tells THEM that and
    # tells the owner nothing at all — the fact lives in a code comment there.
    # It is recoverable (the pair code still works) and that is said here,
    # because a cost with no way out reads as a bigger decision than it is.
    "device-deny": "Say no to {name}? They cannot ask again for a week — the app "
                   "tries to tell them, but that depends on their own "
                   "notification settings. Giving them the pair code still works "
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
        m2 = re.search(r"\b(?:of|for|on|about)\s+(?:the\s+|my\s+)?(.+)$", src, re.I) or \
            (re.search(r"^(?:the\s+|my\s+)?(.+)$", verb_tail, re.I) if verb_tail else None)
        if m2:
            name = m2.group(1)
    if not name:
        return None
    name = re.sub(r"[?.!,]+$", "", name).strip()
    name = re.sub(r"\s+(run|one|research|research run)$", "", name, flags=re.I).strip()
    if not name or name.lower() in _NL_GENERIC_RUN:
        return None
    return name


def _nl_resolve(text: str) -> "tuple[list[str] | None, list[str] | None]":
    """Map a verbatim user message to (argv, None) to execute, or
    (None, user-safe lines) to relay. Ordered — most specific first."""
    t = " ".join((text or "").split())
    low = t.lower().rstrip("?!. ")
    if not low:
        return None, ["What would you like? I can research a topic, check a run’s "
                      "status, fetch its podcast or links, or manage your devices."]

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
        _pairing = re.search(r"\b(pair|pairing|code|codes|connect|add)\b", low)
        _existing = re.search(r"\b(switch to|run (?:it |everything )?on|use|using|"
                              r"select|remove|unlink|forget|delete|ask|asking|"
                              r"request|requesting|borrow)\b", low)
        if _bare or _pairing or (_kw and not _existing):
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
            re.search(rf"\b(add|pair|connect)\b.*\b({_MACHINE_NOUNS})\b", low)
            or re.search(r"\bpair (my|a|the|this)\b", low)):
        return None, ["Paste the access code shown on the computer running Super "
                      "Research (8 characters — dashes optional) and I’ll add it."]

    # 2. Sign-in / connection questions — always a FRESH account check.
    if re.search(r"\b(am i|are we|is (it|this|the agent))\b.*\b(signed?[ -]?in|logg?ed[ -]?in|connected|authenticated)\b", low) or \
            re.search(r"\b(which|what) account\b", low) or "account status" in low or \
            "connection status" in low:
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
        if topic and not re.fullmatch(r"(?:the |my )?(?:status|progress|updates?)", topic, re.I):
            flags: list[str] = []
            ex = re.search(
                r"[,;\s]*\b(?:without|minus|skip(?:ping)?|drop(?:ping)?|leave out|no)\s+"
                r"(?:the\s+|a\s+|any\s+)?(?:video|email|podcast|brief|report|chatgpt|gpt|claude|gemini)s?\b",
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
    _public_kw = re.search(r"\bpublic(?:ly)?\b|\bsomebody else|\bsomeone else"
                           r"|\bother (?:people|persons?|users?)\b", low)
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
    _machine_kw = re.search(rf"\b({_MACHINE_NOUNS})\b", low)
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
    _low_no_rc = re.sub(rf"\bresearch(?:es)?\s+(?:{_MACHINE_NOUNS})\b", "  ", low)
    _artefact_kw = re.search(r"\b(podcasts?|audio|videos?|reports?|briefs?|links?|"
                             r"status|progress|updates?|research(?:es)?|topics?|"
                             r"logs?|results?|runs?|emails?)\b", _low_no_rc)
    _control_kw = re.search(r"\b(stop|end|abort|pause|resume|unpause|retry|skip|"
                            r"drop)\b", low)
    _unlink_kw = re.search(r"\b(unlink|forget)\b", low)
    _mine_kw = re.search(rf"\b(my|mine|our|this)\b(?:\s+\w+){{0,2}}\s+"
                         rf"(?:{_MACHINE_NOUNS})\b", low)
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
    _offering_kw = re.search(r"\b(sharing|offering|discoverable|findable)\b", low)
    # ⛔⛔ THE WORDS FOR HIDING CARRY NO "PUBLIC" IN THEM. "hide my computer",
    # "unlist my mac", "make my pc private", "stop offering my machine" — every
    # one of those fell through to the catch-all or, worse, to rule 3, which
    # quoted "offering my mac" back as a research title and offered to stop it.
    # ⛔⛔ HIDING IS OFTEN SAID WITHOUT THE WORD "PRIVATE" — cross-verify found
    # eight shapes that carry no hiding word at all and every one of them
    # reached the PUBLISH confirm, i.e. the exact opposite of what was asked.
    # "turn off sharing", "disable sharing", "no longer share it", "remove it
    # from the public list", "undo making it public", "it should not be public".
    _hiding_kw = (re.search(r"\b(private|hidden|hide|unlist|unlisted|unpublish|"
                            r"undiscoverable)\b", low)
                  or re.search(r"\b(stop|turn|switch|shut)\b.{0,20}\b(off|offering|"
                               r"sharing|listing|publishing|letting|showing|"
                               r"allowing)\b", low)
                  or re.search(r"\b(disable|unshare|deregister|delist)\b", low)
                  or re.search(r"\b(take|remove|drop|pull)\b.{0,30}"
                               r"\b(off|out of|from)\b.{0,24}\b(list|public|"
                               r"directory)\b", low)
                  or re.search(r"\bundo\b.{0,24}\bpublic\b", low)
                  # ⛔⛔ A NEGATION IN FRONT OF "PUBLIC" IS A HIDE, NOT A PUBLISH.
                  or re.search(r"\b(don'?t|do not|never|no longer|not|shouldn'?t|"
                               r"should not|stop)\b[^.?!]{0,40}\b(public|findable|"
                               r"discoverable|shared?|sharing)\b", low))
    # ⛔⛔ A POLITE IMPERATIVE IS NOT A QUESTION. "can you make my mac public"
    # and "could you hide my mac" are the commonest way anybody asks for either
    # verb, and reading them as state questions answered neither. The
    # discriminator is whether a SETTER follows the politeness, not the opening
    # word — "is my mac public" has no setter and stays a question.
    _polite_imperative = re.match(r"^(?:can|could|would|will|please|do)\s+(?:you\s+)?"
                                  r"(?:please\s+)?(?:make|set|switch|turn|put|hide|"
                                  r"unlist|unpublish|offer|share|publish|disable)\b",
                                  low)
    _asking_state = (re.match(r"^(is|are|does|do|can|could|who|what|which|how|"
                              r"tell me (?:if|whether)|check)\b", low)
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
    _named_target = (re.search(r"\b(?:make|set|switch|turn|put|hide|unlist|"
                               r"unpublish|offer|share|publish|disable|take|"
                               r"remove|drop|pull)\s+"
                               rf"(?:the|my|our|this|that)\s+[\w' -]*"
                               rf"(?:{_MACHINE_NOUNS})\b", low)
                     # ⛔ A QUOTED NAME CARRIES NO ARTICLE, and the picker's own
                     # worked example quotes one: `make “Research computer”
                     # public`. Without this the string the client just told the
                     # person to type reached the browse list.
                     or re.search(r"\b(?:make|set|switch|turn|put|hide|unlist|"
                                  r"unpublish|offer|share|publish|disable)\s+"
                                  rf"[{re.escape(_NL_QUOTE_CHARS)}]", t))
    if (_public_kw or _offering_kw or _hiding_kw) \
            and (_mine_kw or re.search(r"\bmy own\b", low) or _named_target) \
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
        _vis_obj = ""
        _vm = (re.search(rf"\b(?:make|set|switch|turn|put|offer|share|publish|"
                         rf"hide|unlist|unpublish)\s+"
                         rf"[{re.escape(_NL_QUOTE_CHARS)}]([^{re.escape(_NL_QUOTE_CHARS)}]+)",
                         t, flags=re.I)
               or re.search(r"\b(?:make|set|switch|turn|put|offer|share|publish)\s+"
                            r"(.+?)\s+(?:public|private|findable|discoverable|"
                            r"hidden|unlisted)\b", t, flags=re.I)
               or re.search(r"\b(?:hide|unlist|unpublish|delist)\s+(.+?)$",
                            t, flags=re.I)
               or re.search(r"\b(?:take|remove|drop|pull)\s+(.+?)\s+"
                            r"(?:off|out of|from)\b", t, flags=re.I))
        if _vm:
            _vis_obj = re.sub(r"^(?:the|a|an|my|our|this|that)\s+", "",
                              _vm.group(1).strip().strip(_NL_QUOTE_CHARS),
                              flags=re.I).strip()
            _vis_obj = re.sub(r"[?.!,]+$", "", _vis_obj).strip()
            # A bare noun names no machine; neither does a phrase about other
            # people's, and quoting either back is the 7.9-2 defect shape.
            # ⛔ THE TEST IS ON THE CAPTURED OBJECT, NOT ON THE MESSAGE. The
            # first version also cleared the name whenever `_public_kw` matched
            # — which is every publish phrasing there is — so no machine could
            # ever be named. What disqualifies a capture is that IT names no
            # machine: a bare noun, a pronoun, or a phrase about other people's.
            if (re.fullmatch(rf"(?:{_MACHINE_NOUNS}|it|them|one|ones|everything|"
                             rf"me|us|myself)", _vis_obj, flags=re.I)
                    or re.search(r"\bpublic|\bsomebody else|\bsomeone else|"
                                 r"\bother (?:people|persons?|users?)\b",
                                 _vis_obj, flags=re.I)):
                _vis_obj = ""
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
    _negated_decide = re.search(r"\b(don'?t|do not|never|no longer|not|cannot|"
                                r"can'?t|shouldn'?t|should not|won'?t|would not)"
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
            _who = re.sub(r"^(?:the|a|an|that|this|their|his|her|its)\s+", "",
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
            if re.fullmatch(rf"(?:it|them|him|her|us|they|everyone|everybody|"
                            rf"persons?|people|somebody|someone|anyone|anybody|"
                            rf"this|that|here|there|now|yet|access|permission|"
                            rf"default|both|all|everything|one|ones|my|our|"
                            rf"my\s+\w+|our\s+\w+|{_MACHINE_NOUNS})", _who,
                            flags=re.I) or len(_who) > 60:
                _who = ""
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
        _ask_obj = re.sub(r"[,;]?\s+(?:please|thanks|thank you|for me|"
                          r"if (?:i|you) (?:can|could|may|would))\s*$", "",
                          _ask_obj, flags=re.I).strip()
        _ask_obj = re.sub(r"^(?:the|a|an|my|their|its|that|this)\s+", "", _ask_obj,
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
    _ask_obj_is_id = bool(" " not in _ask_obj and len(_ask_obj) >= 8
                          and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*[-_]"
                                           r"[A-Za-z0-9_-]*[A-Za-z0-9]", _ask_obj))
    _ask_is_about_a_machine = bool(
        _public_kw or _machine_kw or _ask_obj_is_id
        or re.search(r"\baccess to\b|\bto use\b|\bpermission\b|\bborrow\b", low))

    if _ask_kw and _ask_obj and _ask_is_about_a_machine and not _ask_obj_is_thing \
            and not _ask_obj_is_pronoun and not _ask_obj_is_category \
            and not _control_kw and not _unlink_kw:
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
    if re.search(r"\b(stop|end|abort|cancel)\b", low) or re.search(r"\bthat.?s enough\b", low):
        name = _nl_run_name(t, re.sub(r"^.*?\b(?:stop|end|abort|cancel)\b", "", t, flags=re.I).strip())
        return None, [_NL_CONFIRMS["stop"].format(name=f"“{name}”" if name else "the current run")]
    if re.search(r"\bpause\b|\bhold (on|it)\b", low):
        name = _nl_run_name(t, re.sub(r"^.*?\bpause\b", "", t, flags=re.I).strip())
        return ["pause"] + ([name] if name else []), None
    if re.search(r"\b(resume|unpause)\b|\bcontinue the paused\b", low):
        name = _nl_run_name(t, re.sub(r"^.*?\b(?:resume|unpause)\b", "", t, flags=re.I).strip())
        return ["resume"] + ([name] if name else []), None
    if re.search(r"\b(retry|try again)\b", low):
        name = _nl_run_name(t, re.sub(r"^.*?\b(?:retry|try again)\b", "", t, flags=re.I).strip())
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
    _q_start = re.match(
        r"\s*(why|is|are|did|does|has|have|what|when|where|who|how"
        # Modal-verb yes/no questions are ASKS, not orders: "can/could/should/
        # would/will/shall/may/do I skip the podcast?" must bail to a relay, not
        # silently skip a phase on the live run (skip is not confirm-gated).
        r"|can|could|should|would|will|shall|may|do|don't|dont)\b",
        low,
    )
    _device_noun = re.search(rf"\b({_MACHINE_NOUNS}|phones?)\b", low)
    if not _q_start and not _device_noun and \
            re.search(r"\b(skip|drop|remove|cut|leave out|without|no)\b", low):
        phases = [p for p in _NL_PHASE_WORDS if p in low]
        agents: list = []
        _agent_adjacent = re.search(
            r"\b(?:skip(?:ping)?|drop(?:ping)?|remove|cut|leave\s+out|without|minus|no)\s+"
            r"(?:the\s+|a\s+|any\s+)?(?:chatgpt|gpt|claude|gemini)\b(?!['’-])"
            r"(?!\s+(?:video|podcast|report|brief|email)\b)", low)
        if _agent_adjacent and not re.search(r"\b(?:research|look into|deep dive on|investigate)\s+\w+", low):
            agents = [a for a in _NL_AGENT_WORDS
                      if re.search(rf"\b{a}\b(?!['’-])(?!\s+(?:video|podcast|report|brief|email)\b)", low)]
        if phases or agents:
            return ["skip"] + phases + agents, None
    if re.search(r"^skip\b|\bskip (it|this|that|the step|the blocker)\b", low):
        return ["skip"], None

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
    _dev_verb = re.search(r"\b(remove|unlink|forget|delete|add|pair|connect|"
                          r"switch to)\b|\brun (?:it |everything )?on\s+\S", low)
    _list_narrow = re.search(r"\b(which|what|list|show|my)\b.*\b(devices?|nodes?)\b", low)
    _list_wide = re.search(rf"\b(which|what|list|show|my)\b.*\b({_MACHINE_NOUNS})\b", low)
    # ⛔ `running` IS NOT IN `_artefact_kw` AND HAD TO BE NAMED. "what's running on
    # my mac" is a question about RUNS; at HEAD the narrow list let it fall through
    # to the progress rule, and the wider one caught it.
    _wide_is_clean = (not _artefact_kw and not _control_kw
                      and not re.search(r"\brunning\b", low))
    if (not _dev_verb and (_list_narrow or (_list_wide and _wide_is_clean))) or \
            low in ("devices", "device list") or "what am i running on" in low:
        return ["devices"], None
    m = re.search(r"\b(?:switch to|run (?:it |everything )?on|use)\s+(?:the\s+|my\s+)?(.+)$", t, flags=re.I)
    # ⛔ `use` IS IN THE GATE NOW BECAUSE IT WAS ALWAYS IN THE CAPTURE. The
    # picker one file up ends every ask with 'Just say: use “<name>”.' — the one
    # phrasing this line did not route, so following the instruction on screen
    # reached "I didn't catch a Super Research request in that". It is gated on a
    # QUOTED name so that "use less video" and "use chatgpt" stay clear of it.
    _bare_use = t[:4].lower() == "use " and t[4:5] in _NL_QUOTE_CHARS
    if m and (re.search(r"\b(switch to|run (it |everything )?on)\b", low) or _bare_use):
        name = re.sub(r"[?.!,]+$", "", m.group(1)).strip()
        # ⛔ A LEADING DEVICE NOUN IS NOT PART OF THE NAME. "switch to the machine
        # LABPC001" carried "machine LABPC001" into a name lookup that matches on
        # name, hostname and substring — none of which contains the word.
        name = _strip_leading_noun(name)
        if _is_bare_machine_noun(name):
            name = ""
        return (["device-use", name] if name else ["devices"]), None
    if re.search(r"\b(remove|unlink|forget|delete)\b", low) and \
            re.search(rf"\b({_MACHINE_NOUNS}|phones?)\b", low):
        # ⛔ FIVE MORE DETERMINERS. The ask branch strips `the|a|an|my|their|its|
        # that|this`; this one stripped only `the|my`, so "remove that computer"
        # and "unlink their laptop" carried the word into a DESTRUCTIVE confirm.
        m = re.search(r"\b(?:remove|unlink|forget|delete)\s+"
                      r"(?:the\s+|a\s+|an\s+|my\s+|their\s+|its\s+|that\s+|this\s+)?(.+)$",
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
        name = name.strip().strip(_NL_QUOTE_CHARS).strip()
        name = _strip_leading_noun(name)
        # ⛔⛔ AND NOT "that device" EITHER. The old fallback was written for a
        # message that named nothing at all; here the person DID name something,
        # it just turned out to be the noun. Confirming "Unlink that device?" and
        # then running a remove with no argument would unlink whichever one the
        # resolver happened to land on. Ask which, and remove nothing until told.
        if _is_bulk_machine_phrase(name):
            # ⛔ UNLINK TAKES EXACTLY ONE MACHINE. Answering a bulk request with
            # "which one?" hides that the thing asked for cannot be done at all.
            return None, ["I unlink one computer at a time. Ask me to list them and "
                          "name the one to remove — nothing is removed until you do."]
        if not name or _is_bare_machine_noun(name):
            return None, ["Which computer should I unlink? Ask me to list them and "
                          "name one — nothing is removed until you do."]
        return None, [_NL_CONFIRMS["device-remove"].format(name=f"“{name}”")]

    # 5. Session + maintenance.
    if re.search(r"\b(uninstall|tear ?down)\b", low) or \
            re.search(r"\b(remove|disconnect)\b.*\b(entirely|completely|fully|everything)\b", low):
        return None, ["Just sign out, or fully remove the skill + bridge from this "
                      "machine? (Sign-out keeps everything installed.)"]
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
    if re.search(r"\b(install|host|set ?up)\b.*\b(backend|super research|here|this (pc|machine|computer))\b", low):
        return None, [_NL_CONFIRMS["install"]]

    # 6. Listing + progress (before research — "results of X" is a status ask).
    if re.search(r"\bwhat('s| is) (running|active)\b|\bactive runs?\b|\banything running\b", low):
        return ["updates"], None
    if re.search(r"\b(list|show|what)\b.*\b(researches|research history|past research(es)?)\b", low) or \
            low in ("list", "my researches", "researches"):
        return ["list"], None
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
    if not _artefact_kw and re.search(
            rf"\b(?:i (?:do not|don'?t|dont) have|i have no|i haven'?t got"
            rf"|i'?ve got no|i (?:do not|don'?t|dont) own)\b[^.?!]*"
            rf"\b(?:{_MACHINE_NOUNS})\b", low):
        return ["devices"], None

    # 7. Nothing matched — user-safe capabilities line (never guess a command).
    #    (Research phrasings were resolved at 2b, before the control rules.)
    # ⛔ THE CAPABILITY LINE IS PART OF THE SURFACE. It is what somebody reads
    # after a phrasing this resolver could not place, so a verb missing from it is
    # a verb the fallback denies having.
    return None, ["I didn’t catch a Super Research request in that. I can research "
                  "a topic, check a run’s status, fetch its podcast or links, list "
                  "your researches, manage your devices, find a public computer and "
                  "ask to use it, and — for a computer you own — answer the people "
                  "asking for it and set whether strangers can find it at all — "
                  "what would you like?"]


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
_DO_FLAGS = frozenset({"--no-video", "--no-email", "--machine", "--agent-log"})


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
    flags = [a for a in rest if a in _DO_FLAGS]
    pos = [a for a in rest if a not in _DO_FLAGS]
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
