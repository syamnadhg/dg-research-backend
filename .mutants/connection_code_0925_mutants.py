"""Mutation harness — the connection code: the link first, the code as the "or", never an access code (Mac brief, 2026-09-25).

⛔⛔ WHAT THIS CODE DECIDES. Whether somebody whose sign-in link won't open — on another
device, say — is handed the short connection code and the page to type it at, in the
same three lines on every surface; whether the code they check on the page is the one
the bridge handed over, character for character; and whether that code, typed where a
computer's ACCESS code goes while its sign-in is pending, is refused before anything
is claimed. Both codes are eight characters and look alike, and the chat now prints
the one.

  S* — the chat client (sr.py): the sign-in lines (`_signin_link_lines`), both doors
       that print them (`login`, a research asked while signed out), the long-code
       fallback, and `device-add`'s reading of the bridge's `reason`.
  L* — the terminal (cli.py): the same lines in `_remote_signin`, the page's real
       button name, and `device add`'s reading of `reason` (`_pair_refusal_key`).
  B* — the bridge (bridge.py): the /device/pair refusal — its place before the
       session check, its normalization, its reason, its sentence and its log line.
  K* — SKILL.md: relay the link AND the code as printed; never pair with the code.

⛔ THE TWO ANCHORS THIS CHANGE MOVED ARE RE-AIMED IN THEIR OWN HARNESSES, not copied
here: stretch45_agent_0827 A4 (the signed-out research door's preface) and
wave795_pair_code T5 (the terminal's pair refusal).

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.

  python .mutants/connection_code_0925_mutants.py
  python .mutants/connection_code_0925_mutants.py S1 L1 B1
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

BRIDGE = "agent/facade/bridge.py"
CLI = "agent/facade/cli.py"
SR = "agent/facade/skill/scripts/sr.py"
SKILL = "agent/facade/skill/SKILL.md"

_HOME = "tests/test_connection_code_0925.py"
# (cwd, suites) per mutated file — every file runs this change's own suite, plus the
# suites that already read the code it touched: the pair tables' drift detector and
# the chat lifecycle (sr.py), the tables and `connect`'s headless path (cli.py), the
# broker handoff and auto-poll (bridge.py), and SKILL.md's length cap.
SUITES = {
    SR: (AGENT, f"{_HOME} tests/test_unlink_copy_795.py tests/test_e2e_lifecycle.py"),
    CLI: (AGENT, f"{_HOME} tests/test_unlink_copy_795.py tests/test_cli_commands.py"),
    BRIDGE: (AGENT, f"{_HOME} tests/test_bridge_remote_login.py tests/test_remote_autopoll.py"),
    SKILL: (AGENT, f"{_HOME} tests/test_skill_commands_resolve.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

MUTANTS = [
    # ═══ S — the chat client ═══════════════════════════════════════════════════
    ("S1", SR, "⛔ AN EMPTY CODE COUNTS AS SHORT — a reply with no code prints \"enter this "
     "connection code: \" and nothing after it",
     [("    if page and 0 < len(code) <= _CONNECTION_CODE_MAX:\n        lines.append(",
       "    if page and len(code) <= _CONNECTION_CODE_MAX:\n        lines.append(")]),
    ("S2", SR, "⛔⛔ THE LENGTH GUARD IS GONE — an older broker's 43-character token is "
     "printed as a \"connection code\" nobody can type or compare",
     [("    if page and 0 < len(code) <= _CONNECTION_CODE_MAX:\n        lines.append(",
       "    if page and 0 < len(code):\n        lines.append(")]),
    ("S3", SR, "the guard's bound moves off twelve — a 12-character code loses its lines",
     [("_CONNECTION_CODE_MAX = 12", "_CONNECTION_CODE_MAX = 11")]),
    ("S4", SR, "⛔⛔ THE LINK IS NO LONGER FIRST — the \"or\" arrives before the thing it is "
     "the alternative to",
     [("    return lines\n\n\ndef cmd_login(args) -> int:",
       "    return lines[1:] + lines[:1]\n\n\ndef cmd_login(args) -> int:")]),
    ("S5", SR, "⛔⛔ THE \"OR\" LINE IS DROPPED — the chat prints only the link again, and a "
     "person whose link won't open has nothing to type",
     [("        lines.append(\"Or, if the link won't open (for example on another device): \"\n"
       "                     f\"go to {page} and enter this connection code: {code}\")\n",
       "")]),
    ("S6", SR, "⛔ THE CHECK IS DROPPED — nobody is asked to compare the code on the page "
     "before tapping Authenticate",
     [("        lines.append(\"Either way, check the page shows the same connection code, \"\n"
       "                     \"then tap Authenticate.\")\n",
       "")]),
    ("S7", SR, "⛔ THE PAGE IS A LITERAL — a local E2E's link and its typed-code page point at "
     "two different sites",
     [("    page = url.split(\"?\", 1)[0]\n    lines = [f\"Log in here: {url}\"]",
       "    page = \"https://superresearch.io/connect\"\n    lines = [f\"Log in here: {url}\"]")]),
    ("S8", SR, "the page is the whole link — \"go to\" names the code-carrying link, not the "
     "page the code is typed at",
     [("    page = url.split(\"?\", 1)[0]\n    lines = [f\"Log in here: {url}\"]",
       "    page = url\n    lines = [f\"Log in here: {url}\"]")]),
    ("S9", SR, "⛔ THE CODE IS REFORMATTED — upper-cased on the way out, so the chat shows a "
     "code the bridge never handed over",
     [("f\"go to {page} and enter this connection code: {code}\")\n        lines.append(\"Either way",
       "f\"go to {page} and enter this connection code: {code.upper()}\")\n        lines.append(\"Either way")]),
    ("S10", SR, "⛔⛔ THE SIGNED-OUT RESEARCH DOOR PRINTS ONLY THE LINK — the one door that "
     "carries a waiting topic loses the connection code",
     [("                    *_signin_link_lines(lbody),",
       "                    f\"  {link}\",")]),
    ("S11", SR, "the long-code fallback says nothing after the link — no word of what to tap",
     [("        if len(lines) == 1:\n", "        if False:\n")]),
    ("S12", SR, "`--json` for a signed-out research drops the code a rendering caller needs",
     [("                    out[\"code\"] = lbody[\"code\"]", "                    pass")]),
    ("S13", SR, "⛔⛔ `device-add` READS ONLY `error` — the bridge's `signin_code` misses the "
     "table and the chat prints \"couldn’t add the device: that's your connection code …\"",
     [("        if isinstance(reason, str) and _PAIR_ERRORS.get(reason):\n            err = reason",
       "        if False:\n            err = reason")]),
    ("S14", SR, "⛔ `device-add` TRUSTS ANY `reason` — the 401 relay's \"revoked\" becomes "
     "\"couldn’t add the device: revoked\" instead of the signed-out sentence",
     [("        if isinstance(reason, str) and _PAIR_ERRORS.get(reason):\n            err = reason",
       "        if isinstance(reason, str):\n            err = reason")]),
    ("S15", SR, "the link line's words change — \"Sign in here:\" in the chat, not the "
     "brief's \"Log in here:\"",
     [("    lines = [f\"Log in here: {url}\"]", "    lines = [f\"Sign in here: {url}\"]")]),
    ("S16", SR, "⛔⛔ THE GUARD IS INVERTED — the live short code loses its lines, and only an "
     "older broker's untypeable token is handed out as a code",
     [("    if page and 0 < len(code) <= _CONNECTION_CODE_MAX:\n        lines.append(",
       "    if page and not (0 < len(code) <= _CONNECTION_CODE_MAX):\n        lines.append(")]),
    ("S17", SR, "⛔⛔ THE GUARD IS WIDENED TO 43 — an older broker's 43-character token passes "
     "as a \"connection code\"",
     [("_CONNECTION_CODE_MAX = 12", "_CONNECTION_CODE_MAX = 43")]),
    ("S18", SR, "⛔⛔ THE LINK LINE IS DROPPED — the \"or\" is all that is left, the alternative "
     "to a link nobody was given",
     [("    lines = [f\"Log in here: {url}\"]\n    if page and",
       "    lines = []\n    if page and")]),
    ("S19", SR, "⛔ THE CHECK COMES BEFORE THE \"OR\" — \"Either way\" names two ways before the "
     "second has been offered",
     [("        lines.append(\"Or, if the link won't open (for example on another device): \"\n"
       "                     f\"go to {page} and enter this connection code: {code}\")\n"
       "        lines.append(\"Either way, check the page shows the same connection code, \"\n"
       "                     \"then tap Authenticate.\")\n",
       "        lines.append(\"Either way, check the page shows the same connection code, \"\n"
       "                     \"then tap Authenticate.\")\n"
       "        lines.append(\"Or, if the link won't open (for example on another device): \"\n"
       "                     f\"go to {page} and enter this connection code: {code}\")\n")]),
    ("S20", SR, "⛔⛔ THE CHAT'S `signin_code` ENTRY IS GONE — the bridge's refusal is worded "
     "\"couldn’t add the device: that's your connection code …\" around a sentence of its own",
     [("    \"signin_code\": \"That’s your connection code — it signs you in, it doesn’t add a \"\n"
       "                   \"computer. Open the link I sent, or type the code at \"\n"
       "                   \"https://superresearch.io/connect\",\n",
       "")]),
    # ═══ L — the terminal ══════════════════════════════════════════════════════
    ("L1", CLI, "⛔ THE TERMINAL'S GUARD TAKES AN EMPTY CODE — \"enter this connection code: \" "
     "and nothing",
     [("    if page and 0 < len(code) <= _CONNECTION_CODE_MAX:\n        b.line(",
       "    if page and len(code) <= _CONNECTION_CODE_MAX:\n        b.line(")]),
    ("L2", CLI, "⛔⛔ THE TERMINAL PRINTS AN OLDER BROKER'S 43-CHARACTER TOKEN as a code to type",
     [("    if page and 0 < len(code) <= _CONNECTION_CODE_MAX:\n        b.line(",
       "    if page and 0 < len(code):\n        b.line(")]),
    ("L3", CLI, "⛔⛔ THE TERMINAL DROPS THE \"OR\" LINE — its copy drifts from the chat's",
     [("        b.line(\"Or, if the link won't open (for example on another device): \"\n"
       "               f\"go to {page} and enter this connection code: {code}\")\n",
       "")]),
    ("L4", CLI, "⛔ THE TERMINAL'S PAGE IS A LITERAL — its link and its typed-code page can "
     "disagree",
     [("    page = url.split(\"?\", 1)[0]\n    b.line(f\"Log in here: {url}\")",
       "    page = \"https://superresearch.io/connect\"\n    b.line(f\"Log in here: {url}\")")]),
    ("L5", CLI, "⛔ \"Approve & connect\" IS BACK — a button label the page has never shown",
     [("        b.dim(\"Sign in with your Super Research Google account, then tap Authenticate.\")",
       "        b.dim(\"Sign in with your Super Research Google account, then tap Approve & connect.\")")]),
    ("L6", CLI, "\"then tap Authenticate.\" twice in a row — the check line and the dim line "
     "both say it",
     [("        b.dim(\"Sign in with your Super Research Google account.\")",
       "        b.dim(\"Sign in with your Super Research Google account, then tap Authenticate.\")")]),
    ("L7", CLI, "⛔⛔ `device add` READS ONLY `error` — the bridge's raw sentence reaches the "
     "screen instead of the terminal's own",
     [("    if isinstance(reason, str) and reason in _PAIR_FAILURES:\n        return reason",
       "    if False:\n        return reason")]),
    ("L8", CLI, "⛔ `device add` TRUSTS ANY `reason` — \"revoked\" loses the signed-out "
     "sentence and its `agent login`",
     [("    if isinstance(reason, str) and reason in _PAIR_FAILURES:\n        return reason",
       "    if isinstance(reason, str):\n        return reason")]),
    ("L9", CLI, "⛔ THE TERMINAL DROPS THE CHECK — nobody at the terminal is asked to compare "
     "the code on the page before tapping Authenticate",
     [("        b.line(\"Either way, check the page shows the same connection code, \"\n"
       "               \"then tap Authenticate.\")\n",
       "")]),
    ("L10", CLI, "the terminal's link line says \"Sign in here:\" again — its old words, not "
     "the chat's \"Log in here:\"",
     [("    b.line(f\"Log in here: {url}\")\n", "    b.line(f\"Sign in here:  {url}\")\n")]),
    ("L11", CLI, "⛔⛔ THE TERMINAL'S LINK IS NO LONGER FIRST — the \"or\" arrives before the "
     "thing it is the alternative to",
     [("    b.line(f\"Log in here: {url}\")\n    if page and", "    if page and"),
      ("    if not poll:\n        b.dim(\"Approve it in your browser",
       "    b.line(f\"Log in here: {url}\")\n"
       "    if not poll:\n        b.dim(\"Approve it in your browser")]),
    ("L12", CLI, "⛔⛔ THE TERMINAL'S GUARD IS INVERTED — the live short code is never shown, "
     "an older broker's token is",
     [("    if page and 0 < len(code) <= _CONNECTION_CODE_MAX:\n        b.line(",
       "    if page and not (0 < len(code) <= _CONNECTION_CODE_MAX):\n        b.line(")]),
    ("L13", CLI, "⛔⛔ THE TERMINAL'S GUARD IS WIDENED TO 43 — an older broker's token is printed "
     "as a code to type",
     [("_CONNECTION_CODE_MAX = 12", "_CONNECTION_CODE_MAX = 43")]),
    ("L14", CLI, "the terminal's bound moves off twelve — a 12-character code the chat shows, "
     "the terminal hides",
     [("_CONNECTION_CODE_MAX = 12", "_CONNECTION_CODE_MAX = 11")]),
    ("L15", CLI, "⛔⛔ THE TERMINAL DROPS THE LINK LINE — an \"or\" with nothing before it",
     [("    b.line(f\"Log in here: {url}\")\n    if page and", "    if page and")]),
    ("L16", CLI, "⛔ THE TERMINAL'S CHECK COMES BEFORE ITS \"OR\" — the two copies disagree on "
     "the order",
     [("        b.line(\"Or, if the link won't open (for example on another device): \"\n"
       "               f\"go to {page} and enter this connection code: {code}\")\n"
       "        b.line(\"Either way, check the page shows the same connection code, \"\n"
       "               \"then tap Authenticate.\")\n",
       "        b.line(\"Either way, check the page shows the same connection code, \"\n"
       "               \"then tap Authenticate.\")\n"
       "        b.line(\"Or, if the link won't open (for example on another device): \"\n"
       "               f\"go to {page} and enter this connection code: {code}\")\n")]),
    ("L17", CLI, "⛔ \"Approve & connect\" IS BACK IN THE CHECK LINE — the short-code path names "
     "a button the page has never shown",
     [("               \"then tap Authenticate.\")\n"
       "        b.dim(\"Sign in with your Super Research Google account.\")",
       "               \"then tap Approve & connect.\")\n"
       "        b.dim(\"Sign in with your Super Research Google account.\")")]),
    ("L18", CLI, "⛔⛔ THE TERMINAL'S `signin_code` ENTRY IS GONE — `device add` prints the "
     "bridge's raw sentence, or the bare identifier",
     [("    \"signin_code\": \"that's your connection code, for signing in — open the sign-in \"\n"
       "                   \"link, or type the code at https://superresearch.io/connect\",\n",
       "")]),
    # ═══ B — the bridge ════════════════════════════════════════════════════════
    ("B1", BRIDGE, "⛔⛔ THE REFUSAL MOVES BEHIND THE SESSION CHECK — the usual case (signed "
     "out, sign-in pending) reads \"not signed in\", and the fresh sign-in that invites "
     "voids the code on the page they already have open",
     [("            flow = state.remote\n            key = _code_key(code)\n",
       "            if self._account() is None:\n                return\n"
       "            flow = state.remote\n            key = _code_key(code)\n")]),
    ("B2", BRIDGE, "⛔⛔ THE REFUSAL IS OFF — the connection code goes to the claim route: "
     "\"no computer is waiting for that code\", and a signed-in try spends one of five",
     [("            if (flow is not None and flow.state == \"pending\" and key\n",
       "            if (False and flow.state == \"pending\" and key\n")]),
    ("B3", BRIDGE, "⛔ NO NORMALIZATION — only the code typed exactly as printed is caught; "
     "\"wdjb-mjht\" or \"WDJBMJHT\" is claimed",
     [("                    and key == _code_key(flow.code)):",
       "                    and code == flow.code):")]),
    ("B4", BRIDGE, "⛔⛔ THE REFUSAL CARRIES NO `reason` — both clients miss their table entry "
     "and print the bridge's sentence as a bare failure",
     [("                self._json(400, {\"reason\": \"signin_code\",",
       "                self._json(400, {\"why\": \"signin_code\",")]),
    ("B5", BRIDGE, "the refusal names a literal page — a local E2E's refusal sends the person "
     "to production",
     [("                page = (flow.verify_url or \"\").split(\"?\", 1)[0] or _CONNECT_PAGE",
       "                page = _CONNECT_PAGE")]),
    ("B6", BRIDGE, "⛔ A COMMA GLUED TO THE URL — the brief's literal \", not here\"; a chat "
     "links the comma and \"/connect,\" is a 404",
     [("                                          f\"{page} — not here\"})",
       "                                          f\"{page}, not here\"})")]),
    ("B7", BRIDGE, "⛔ THE CODE GOES INTO bridge.log — which is uploaded to support",
     [("                         \"connection code, not an access code (nothing claimed)\")",
       "                         \"connection code, not an access code (nothing claimed): %s\", code)")]),
    ("B8", BRIDGE, "the refusal is silent in the log — nothing in bridge.log says why a pair "
     "attempt stopped",
     [("                log.info(\"device pair: refused — that was the pending sign-in's \"\n"
       "                         \"connection code, not an access code (nothing claimed)\")\n",
       "")]),
    ("B9", BRIDGE, "⛔ THE REFUSAL OUTLIVES ITS SIGN-IN — an expired or failed flow's code is "
     "refused too (re-aimed 2026-09-25: a CONNECTED flow's code is refused now, by owner "
     "decision, but in its own words and only for the code's life)",
     [("            if (flow is not None and flow.state == \"pending\" and key\n",
       "            if (flow is not None and key\n")]),
    ("B9b", BRIDGE, "⛔ THE JUST-CONNECTED REFUSAL GOES — a code pasted right after signing in "
     "comes back as a bad computer code again (owner, 2026-09-25)",
     [("            if (flow is not None and flow.state == \"connected\" and key\n",
       "            if (False and flow is not None and flow.state == \"connected\" and key\n")]),
    ("B9c", BRIDGE, "the just-connected refusal outlives the code — refused forever after a "
     "sign-in, until a logout",
     [("                    and key == _code_key(flow.code) and time.time() < flow.expires_at):",
       "                    and key == _code_key(flow.code)):")]),
    ("B9d", SR, "the chat's table loses the just-connected wording, so the bridge's raw "
     "sentence or a generic failure is printed",
     [("    \"signin_code_used\": \"That’s your connection code — you’re already signed in with \"\n",
       "    \"zz_unused\": \"That’s your connection code — you’re already signed in with \"\n")]),
    ("B10", BRIDGE, "⛔⛔ CLAIMED BEFORE IT IS REFUSED — a signed-in person's connection code "
     "goes to the claim route first (one of its five tries spent), and the refusal "
     "arrives after the damage",
     [("            flow = state.remote\n            key = _code_key(code)\n",
       "            if state.session is not None:\n"
       "                _fe_api_post(state.session, \"/api/devices/claim\", {\"code\": code})\n"
       "            flow = state.remote\n            key = _code_key(code)\n")]),
    ("B11", BRIDGE, "⛔ HALF A NORMALIZATION — upper-cased but dashes and spaces kept, so "
     "\"WDJBMJHT\" or \"WDJB MJHT\" is claimed",
     [("    return re.sub(r\"[^A-Z0-9]\", \"\", str(value or \"\").upper())",
       "    return str(value or \"\").upper()")]),
    ("B12", BRIDGE, "⛔ NO UPPER-CASING — a lower-case code normalizes to nothing and is claimed",
     [("    return re.sub(r\"[^A-Z0-9]\", \"\", str(value or \"\").upper())",
       "    return re.sub(r\"[^A-Z0-9]\", \"\", str(value or \"\"))")]),
    # ═══ K — SKILL.md ══════════════════════════════════════════════════════════
    ("K1", SKILL, "⛔⛔ THE MODEL IS NO LONGER TOLD THE CONNECTION CODE ISN'T AN ACCESS CODE — "
     "and the rest of the file sends any bare 8-character code to `device-add`",
     [("  connection code is typed only at superresearch.io/connect — it is not an access\n"
       "  code: **never** run `device-add` with it. The proactive",
       "  connection code is typed only at superresearch.io/connect. The proactive")]),
    ("K2", SKILL, "⛔⛔ THE LOGIN NOTE SAYS \"relay the sign-in link\" AGAIN — the model drops "
     "the code lines the client printed",
     [("- **login** → relay the link AND the connection code exactly as it prints them, link\n"
       "  first; never shorten, invent or reformat the code.",
       "- **login** → relay the sign-in link.")]),
    ("K3", SKILL, "⛔ \"one message: the click-to-approve link\" — the handoff paragraph "
     "licenses relaying the link alone",
     [("the link and connection code lines\nthe client returned, as printed.",
       "the click-to-approve link\nthe client returned.")]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 900


def green(cwd, suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    for cwd, suites in sorted({SUITES[f] for f in files}, key=str):
        if not green(cwd, suites):
            print(f"⛔ BASELINE RED ({suites}) — fix the suite before mutating anything.")
            sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, fname, why, edits in selected:
        path = ROOT / fname
        raw = ORIGINALS[fname]
        crlf = b"\r\n" in raw
        try:
            mutated = raw.decode("utf-8").replace("\r\n", "\n")
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as se:
                    raise AssertionError(f"mutant does not compile: {se}")
            path.write_bytes((mutated.replace("\n", "\r\n") if crlf else mutated)
                             .encode("utf-8"))
            if green(*SUITES[fname]):
                survivors.append(mid)
                print(f"  {mid:4} ✗ SURVIVED — {why}")
            else:
                print(f"  {mid:4} ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (fault)")
            print(f"  {mid:4} ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_bytes(raw)

    for f in files:
        if _digest((ROOT / f).read_bytes()) != DIGESTS[f]:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
