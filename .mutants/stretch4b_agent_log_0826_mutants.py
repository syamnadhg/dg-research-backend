"""Mutation harness for stretch 4B — the agent's own log gets out.

⛔ WHAT THIS CODE DECIDES. Whether a person can find the agent's log, make it say
something, and send it — and whether sending it can ever leave a readable file the
privacy button cannot reach.

⭐⭐ THE SHARPEST MUTANTS HERE:
  V2      — `or config.VERBOSE` goes. The switch still exists, still parses, still
            has tests that pass — and changes nothing on the only install that
            matters, because the pinned launcher runs `main(['serve'])` with no
            flag. A feature that works everywhere except in production.
  DR3     — the log row moves BACK below the bridge check, where `cmd_doctor`
            returns early. The person whose bridge will not start — who needs the
            file more than anybody — stops being told where it is. That is exactly
            the hole the startup banner already had.
  U1/U2   — the upload happens without the row, or with a row that names another
            computer. Either one puts the object in a folder Clear-logs will never
            list, which is a readable log with nothing able to delete it. The 30-day
            bucket rule is then the only reaper, and the button has lied.
  U5      — the tail becomes the HEAD, so an oversized log sends the oldest bytes
            and reports success. The upload works perfectly and carries nothing
            about what just happened.
  L1      — the poll's catch goes back to DEBUG and to calling every failure a
            "transient transport blip". A persistent broker 500 then leaves nothing
            at the default level and is mislabelled at the verbose one.
  L2      — the expiry stops logging. The most common unsuccessful sign-in leaves
            no trace at all, which is precisely what somebody would be sending the
            log to explain.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⚠ THREE PROGRAMS, AND ALL THREE MUST BE GREEN. The bridge and its terminal are the
agent package; the fourth client is the fork, with its own virtualenv; and the
receiving route and the delete side are the web app, which is JavaScript. A harness
that ran fewer legs would report every mutant outside its own leg as killed.

    .venv/bin/python .mutants/stretch4b_agent_log_0826_mutants.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORK = ROOT.parent / "dg-hermes-fleet"
APP = ROOT.parent / "dg-research"

AGENT_SUITES = ("tests/test_agent_log_out_0826.py "
                "tests/test_send_logs_cli_0825.py "
                "tests/test_send_logs_agent_0825.py "
                "tests/test_send_logs_skill_0825.py "
                "tests/test_sr_client.py "
                "tests/test_cli_commands.py "
                "tests/test_logsetup.py "
                "tests/test_remote_autopoll.py")

FORK_SUITES = "skills/tests/test_super_research_skill.py"

# ⛔ The app leg is TWO files and not the whole suite: the two rules suites SKIP
# without an emulator, which vitest reports as failed FILES, so a whole-suite run
# is red on this machine for a reason that has nothing to do with any mutant here.
APP_SUITES = "tests/unit/agentLogRoute.test.ts tests/unit/logBundles.test.ts"

BRIDGE = "agent/facade/bridge.py"
CLI = "agent/facade/cli.py"
CONFIG = "agent/facade/config.py"
PREFS_F = "agent/facade/prefs.py"
SR = "agent/facade/skill/scripts/sr.py"
OURS = (BRIDGE, CLI, CONFIG, PREFS_F, SR)

FORK_SR = "skills/super-research/scripts/sr.py"
THEIRS = (FORK_SR,)

ROUTE = "src/app/api/logs/agent-log/route.ts"
LIMITS = "src/lib/agent-log-limits.ts"
BUNDLES = "src/lib/logBundles.ts"
APPS = (ROUTE, LIMITS, BUNDLES)

SURVIVOR_CONFIRMATIONS = 2

ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ V — the switch that makes the log worth reading ════════════
    ("V1", CONFIG, "under",
     "the switch stops reading the environment, so the only way to raise the "
     "level is a flag the pinned launcher does not pass",
     [('VERBOSE: bool = os.environ.get("SUPER_AGENT_VERBOSE", "").strip().lower() in (\n    "1", "true", "yes", "on",\n)',
       'VERBOSE: bool = False')]),
    ("V2", CLI, "under",
     "⛔⛔ THE SWITCH EXISTS AND CHANGES NOTHING IN PRODUCTION. `or config.VERBOSE` "
     "goes, so an autostarted bridge — which runs `main(['serve'])` with no flag — "
     "is permanently at the default level however the variable is set",
     [('        verbose=(getattr(args, "verbose", False) or config.VERBOSE\n                 or prefs.get_verbose()),',
       '        verbose=getattr(args, "verbose", False),')]),
    ("V3", CONFIG, "over",
     "⛔ any non-empty value turns it on, so `SUPER_AGENT_VERBOSE=0` and "
     "`=false` — the two things a person writes to turn something OFF — turn it on",
     [('VERBOSE: bool = os.environ.get("SUPER_AGENT_VERBOSE", "").strip().lower() in (\n    "1", "true", "yes", "on",\n)',
       'VERBOSE: bool = bool(os.environ.get("SUPER_AGENT_VERBOSE", "").strip())')]),

    # ═══ X — the pref, which is the ONLY switch a pinned bridge can see ═════
    #
    # ⛔⛔ THE ENV VAR SHIPPED AS THE FIX FOR THIS AND COULD NOT REACH THE BRIDGE.
    # `autostart.py` writes no SUPER_AGENT_VERBOSE into any launcher — the macOS
    # plist has no `EnvironmentVariables` key at all — and a LaunchAgent inherits no
    # shell profile. Found by cross-verification, after V1-V3 had all been killed
    # against a switch that was inert in production.
    ("X1", CLI, "under",
     "⛔⛔ `or prefs.get_verbose()` goes, so the ONLY switch a pinned bridge can see "
     "is gone and the feature is back to being inert on the recommended install",
     [('        verbose=(getattr(args, "verbose", False) or config.VERBOSE\n                 or prefs.get_verbose()),',
       '        verbose=(getattr(args, "verbose", False) or config.VERBOSE),')]),
    ("X2", PREFS_F, "under",
     "the pref stops being read, so `agent verbose on` writes a setting nothing "
     "consults — a switch with a receipt and no effect",
     [("    return bool(load().get(_VERBOSE))", "    return False")]),
    ("X3", PREFS_F, "under",
     "turning it OFF leaves the key in place, so a person who turned detailed "
     "logging off keeps writing a detailed log",
     [("        if on:\n            prefs[_VERBOSE] = True\n        elif prefs.pop(_VERBOSE, None) is None:\n            return",
       "        if on:\n            prefs[_VERBOSE] = True\n        elif True:\n            return")]),
    ("X4", CLI, "over",
     "⛔ doctor names the ENVIRONMENT VARIABLE again — unactionable on the "
     "recommended install, so somebody sets it, restarts, sees no change, and stops "
     "looking for the real answer",
     [('        b.dim("              for more detail:  superresearch-agent verbose on")',
       '        b.dim("              for more detail:  SUPER_AGENT_VERBOSE=1, then restart")')]),
    ("X5", CLI, "over",
     "`agent verbose` accepts anything that is not \"off\" as ON, so a typo turns "
     "detailed logging on and reports success",
     [('    if want not in ("on", "off"):', '    if False:'),
      ('    prefs.set_verbose(want == "on")', '    prefs.set_verbose(want != "off")')]),

    # ═══════════ DR — doctor names it, and names it in time ═════════════════
    ("DR1", CLI, "under",
     "doctor stops naming the log at all, so the path returns to being reachable "
     "only through a banner that prints to /dev/null on the pinned install",
     [("    _doctor_log_row()\n\n    health = _bridge_get", "    health = _bridge_get")]),
    ("DR2", CLI, "under",
     "the line saying the log is NOT in a support bundle goes, so somebody who "
     "sent a bundle assumes this went with it and waits on evidence nobody has",
     [('    b.dim("              not sent with a support bundle — this file stays on this host")\n', "")]),
    ("DR3", CLI, "over",
     "⛔⛔ THE ROW MOVES BELOW THE BRIDGE CHECK, where `cmd_doctor` returns early — "
     "so the person whose bridge will not start, who needs this file more than "
     "anybody, is the one person never told where it is. The exact hole the startup "
     "banner already had, reintroduced by a placement that looks tidier. ⭐ This "
     "genuinely MOVES the call: the first version of this mutant only deleted it, "
     "which made it a duplicate of DR1 and its own description untrue",
     [("    _doctor_log_row()\n\n    health = _bridge_get", "    health = _bridge_get"),
      ('    _doctor_row("bridge", True, "up")',
       '    _doctor_log_row()\n    _doctor_row("bridge", True, "up")')]),
    ("DR4", CLI, "under",
     "the way to turn verbose on stops being printed, so the switch exists and "
     "nothing anywhere tells a person it does",
     [('    if not (config.VERBOSE or prefs.get_verbose()):\n        b.dim("              for more detail:  superresearch-agent verbose on")',
       '    if False:\n        pass')]),
    ("DR5", CLI, "over",
     "an absent log is reported as a healthy one, so somebody is sent looking for "
     "contents that were never written",
     [('    _doctor_row("log", size is not None, detail, warn_only=size is None)',
       '    _doctor_row("log", True, detail)')]),

    # ═══════════ L — the sign-in path says what happened ════════════════════
    ("L1", BRIDGE, "over",
     "⛔⛔ back to DEBUG and to calling everything a transient blip. A persistent "
     "broker 500, and 'approved but sent no custom token', both leave NOTHING at "
     "the default level and are mislabelled at the verbose one — then surface as "
     "an expiry, which is not what happened",
     [('        log.info("remote poll failed, still waiting: %s", e)',
       '        log.debug("remote poll transient error: %s", e)')]),
    ("L2", BRIDGE, "under",
     "⛔ the ordinary expiry goes silent again. Somebody who never finished in the "
     "browser is the most common unsuccessful sign-in there is, and it left no "
     "trace at all — which is exactly what they would be sending the log to explain",
     [('        log.info("remote login expired before approval (never confirmed in the browser)")\n', "")]),

    # ═══════════ U — the upload, and the order it may not break ═════════════
    ("U1", BRIDGE, "under",
     "⛔⛔ THE ROW CHECK GOES. The log is uploaded before the machine's bundle has "
     "landed, into a folder no row names — and Clear-logs lists each ROW's folder, "
     "so that is a readable log the privacy button can never reach",
     [('            if not isinstance(row, dict):\n                # The machine has not answered yet.',
       '            if False:\n                # The machine has not answered yet.')]),
    ("U2", BRIDGE, "over",
     "⛔⛔ a row with no device recorded is accepted, so the object goes to "
     "`logs/{uid}//{code}/…` — a path no listing will ever produce",
     [('            if not device_id:\n                self._json(409, {"reason": "bundle_not_landed",',
       '            if False:\n                self._json(409, {"reason": "bundle_not_landed",')]),
    ("U3", BRIDGE, "over",
     "an empty log is uploaded anyway, leaving a zero-byte object that says a "
     "log was sent when there was nothing to send",
     [('            if not blob:', '            if False:')]),
    ("U4", BRIDGE, "under",
     "an upload failure is reported as a success, so the person believes evidence "
     "went that never left the machine",
     [('            if status != 200:', '            if False:')]),
    ("U5", BRIDGE, "over",
     "⛔⛔ THE TAIL BECOMES THE HEAD. An oversized log sends its OLDEST bytes and "
     "reports success — the transport works perfectly and carries nothing about "
     "the thing that just happened",
     [("            if size > cap:\n                fh.seek(size - cap)",
       "            if size > cap:\n                fh.seek(0)")]),
    ("U6", BRIDGE, "under",
     "the partial first line is kept, so what somebody opens first is half a "
     "record with no timestamp",
     [("                fh.readline()\n", "")]),
    ("U7", BRIDGE, "over",
     "the cap goes, so a log that outgrew its rotation is sent whole and refused "
     "by the receiving route — a wasted upload reported as a failure to send",
     [("_AGENT_LOG_MAX_BYTES = 8 * 1024 * 1024", "_AGENT_LOG_MAX_BYTES = 64 * 1024 * 1024")]),
    ("U8", BRIDGE, "under",
     "the support code stops being validated, so a caller-shaped path reaches the "
     "lookup — this route talks to the Admin SDK, which evaluates no rules at all",
     [('            code = str(body.get("code") or "").strip().upper()\n            if not _SUPPORT_CODE_RE.match(code):\n                self._json(400, {"error": "that isn\'t a support code"})\n                return',
       '            code = str(body.get("code") or "").strip().upper()')]),

    # ═══════════ O — the offer, in the clients that word it ═════════════════
    ("O1", CLI, "under",
     "the terminal stops saying the agent log is NOT included, so silence has to "
     "be interpreted — and in the other client silence means something else",
     [('    else:\n        print("The agent\'s own log on this host is NOT included.")',
       '    else:\n        pass')]),
    ("O2", CLI, "over",
     "⛔ the log is sent on the --no-wait path, before the row exists — the one "
     "ordering this feature may not break, reintroduced by the flag that means "
     "\"do not wait for the row\"",
     [('        if agent_log:\n            # ⛔ NOT SENT ON THIS PATH, AND SAID SO.',
       '        if agent_log:\n            _send_agent_log(code)\n        if False:\n            # ⛔ NOT SENT ON THIS PATH, AND SAID SO.')]),
    ("O3", CLI, "over",
     "a failed agent-log send changes the exit code, so a bundle that arrived is "
     "reported as a command that failed",
     [('    rc = _await_bundle(code, args.wait)\n    if agent_log:\n        _send_agent_log(code)\n    return rc',
       '    rc = _await_bundle(code, args.wait)\n    if agent_log:\n        _send_agent_log(code)\n        return 1\n    return rc')]),
    ("O4", SR, "under",
     "our chat client stops saying either way, so its plan is silent about a file "
     "that may or may not be going",
     [('        else:\n            lines.append("The agent’s own log is not included.")',
       '        else:\n            pass')]),
    ("O5", SR, "over",
     "the natural-language route sends the agent log whenever anybody asks about "
     "logs at all — the same over-reading that is deliberately kept away from the "
     "computer's own records",
     [('        if re.search(r"\\b(agent|bridge)(?:’s|\'s)?\\s+(own\\s+)?(log|logs)\\b", low) or \\\n                re.search(r"\\bagent\\s+log\\b", low):\n            argv.append("--agent-log")',
       '        argv.append("--agent-log")')]),
    ("O6", FORK_SR, "under",
     "the fourth client stops saying either way",
     [('        else:\n            _say("The log from the program running this chat is not included.")',
       '        else:\n            pass')]),
    ("O7", FORK_SR, "over",
     "⛔ the fourth client calls it \"that computer's own records\" — this file's "
     "phrase for the RESEARCH computer, six lines above — so the message names the "
     "wrong machine in the one place whose job is to be exact about which",
     [('            _say("Plus the log from the program running this chat — a record of "\n                 "connecting and signing in, not any of their research.")',
       '            _say("Plus that computer\'s own log — a record of "\n                 "connecting and signing in, not any of their research.")')]),

    # ═══════════ A — the receiving route (the web app) ══════════════════════
    ("A1", ROUTE, "under",
     "⛔⛔ the route stops requiring the bundle row, so a caller can write into any "
     "folder name it likes — including one no row will ever name, where Clear-logs "
     "cannot look",
     [("  if (!row) {\n    return NextResponse.json({ error: \"no_such_bundle\" }, { status: 404 });\n  }",
       "  if (false) {\n    return NextResponse.json({ error: \"no_such_bundle\" }, { status: 404 });\n  }")]),
    ("A2", ROUTE, "under",
     "⛔⛔ the device check goes, so the object lands in a folder the row does not "
     "name and the privacy button never finds it",
     [('  if (row.deviceId !== deviceId) {', '  if (false) {')]),
    ("A3", ROUTE, "over",
     "⛔⛔ the uid comes from a header instead of the verified token, so a caller "
     "writes into somebody else's tree",
     [("  const uid = caller.uid;", '  const uid = header(req, "x-uid", 128) || caller.uid;')]),
    ("A4", ROUTE, "under",
     "the caller stops being verified at all — an Admin-SDK writer with no "
     "authentication in front of it",
     [("  const caller = await verifyRequest(req);\n  if (!caller) {",
       "  const caller = (await verifyRequest(req)) ?? { uid: \"anon\" };\n  if (false) {")]),
    ("A5", ROUTE, "over",
     "⛔ the revoke-checking verifier is swapped for a signature-only one, so an "
     "upload is honoured for up to an hour after Sign out everywhere",
     [("import { adminDb, adminStorage, verifyRequest } from \"@/lib/firebase-admin\";",
       "import { adminDb, adminStorage, adminAuth } from \"@/lib/firebase-admin\";\nconst verifyRequest = async (r: NextRequest) => {\n  const t = (r.headers.get(\"authorization\") ?? \"\").slice(7);\n  try { return { uid: (await adminAuth().verifyIdToken(t)).uid }; } catch { return null; }\n};")]),
    ("A6", LIMITS, "over",
     "⛔⛔ the filename becomes bundle.zip. The Admin SDK bypasses rules, so this "
     "name is the only thing between the agent's log and the machine's own "
     "evidence — and the machine's update on its own bundle.zip is deliberately "
     "allowed, so they clobber each other both ways",
     [('export const AGENT_LOG_FILENAME = "agent-log.txt";',
       'export const AGENT_LOG_FILENAME = "bundle.zip";')]),
    ("A7", LIMITS, "under",
     "the support code stops being shape-checked, so a path fragment reaches the "
     "object name — there is no rule engine behind this route to catch it",
     [("export function isSupportCode(code: string): boolean {\n  return SUPPORT_CODE_RE.test(code);\n}",
       "export function isSupportCode(code: string): boolean {\n  return code.length > 0;\n}")]),
    ("A8", LIMITS, "over",
     "the cap is raised to the device path's 64 MB, which is sixty-four times what "
     "the file can hold — a hole rather than a limit",
     [("export const MAX_AGENT_LOG_BYTES = 8 * 1024 * 1024;",
       "export const MAX_AGENT_LOG_BYTES = 64 * 1024 * 1024;")]),
    ("A9", ROUTE, "under",
     "the body cap stops being enforced on bytes actually read",
     [("  const bytes = await readCapped(req, MAX_AGENT_LOG_BYTES);\n  if (bytes === null) {",
       "  const bytes = await readCapped(req, Number.MAX_SAFE_INTEGER);\n  if (bytes === null) {")]),
    ("A10", ROUTE, "under",
     "the rate limit goes, so an unbounded number of 8 MB bodies is the cost of "
     "one account behaving badly",
     [("  const gate = await checkAndIncrement(`agent-log:${uid}`, 10, 60 * 60 * 1000);\n  if (!gate.allowed) {",
       "  const gate = { allowed: true };\n  if (!gate.allowed) {")]),

    # ═══════════ C — the delete side, which ships first ═════════════════════
    ("C1", BUNDLES, "under",
     "⛔⛔ back to deleting only the filename the row knows. A sibling object stays "
     "in the bucket after the privacy button reports the bundle cleared — and so "
     "does the machine's own bundle whenever a lost status write left the row with "
     "no path, which is how the button manufactured its own orphan",
     [("    for (const path of await folderContents(uid, deviceId, row)) {",
       "    for (const path of (row.objectPath ? [row.objectPath] : [])) {")]),
    ("C2", BUNDLES, "over",
     "⛔ the prefix loses a segment, so the listing asks for `logs/{uid}/{deviceId}` "
     "— which the rules deny, because {fileName} is a single-segment wildcard. "
     "Every clear then falls back to the row's own path, for every user, always",
     [("  const prefix = `logs/${uid}/${row.deviceId || deviceId}/${row.code}`;",
       "  const prefix = `logs/${uid}/${row.deviceId || deviceId}`;")]),
    ("C3", BUNDLES, "under",
     "a listing failure deletes nothing instead of falling back to the path the "
     "row can name — a completeness gain traded for a regression",
     [("    console.warn(`[logBundles] could not list ${prefix}, falling back to the row:`, err);\n    return row.objectPath ? [row.objectPath] : [];",
       "    console.warn(`[logBundles] could not list ${prefix}, falling back to the row:`, err);\n    return [];")]),
    ("C4", BUNDLES, "under",
     "the row's own path is no longer added when the listing misses it, so an "
     "object written moments ago survives a clear that reports success",
     [("    if (row.objectPath && !found.includes(row.objectPath)) found.push(row.objectPath);\n", "")]),
    ("C5", BUNDLES, "over",
     "the row is deleted even when one object in its folder survived, which is "
     "what makes a readable file INVISIBLE — the precise failure the object-first "
     "order exists to avoid, now able to happen per-sibling",
     [("    if (objectSurvived) continue;", "    if (false) continue;")]),
]


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", *OURS, "agent/tests"], cwd=ROOT).stdout
    rows = [f"[be] {ln}" for ln in out.splitlines() if ln and not ln.startswith("?? ")]
    out2 = sh(["git", "status", "--porcelain", "--", *THEIRS, "skills/tests"], cwd=FORK).stdout
    rows += [f"[fork] {ln}" for ln in out2.splitlines() if ln and not ln.startswith("?? ")]
    out3 = sh(["git", "status", "--porcelain", "--", *APPS, "tests/unit"], cwd=APP).stdout
    rows += [f"[app] {ln}" for ln in out3.splitlines() if ln and not ln.startswith("?? ")]
    return rows


def run_tests() -> bool:
    """Three programs, and all three must be green.

    ⛔ The app leg runs TWO FILES rather than the suite. The two rules suites skip
    without an emulator, and vitest counts an all-skipped file as a FAILED file — so
    a whole-suite run is red on this machine for a reason no mutant here can cause.
    A tolerance is only meaningful against the selection it was measured on: narrow
    the selection until it is clean, then demand clean.
    """
    purge_pycache(ROOT)
    agent_env = {**ENV, "PYTHONPATH": str(ROOT / "agent")}
    agent = sh([sys.executable, "-B", "-m", "pytest", *AGENT_SUITES.split(),
                "-q", "-p", "no:cacheprovider"], cwd=ROOT / "agent", env=agent_env)
    if agent.returncode != 0:
        return False
    purge_pycache(FORK)
    fork_py = FORK / ".venv" / "bin" / "python"
    if not fork_py.exists():
        raise AssertionError(f"the fork's virtualenv is missing at {fork_py}")
    fork = sh([str(fork_py), "-B", "-m", "pytest", FORK_SUITES,
               "-q", "-p", "no:cacheprovider"], cwd=FORK, env=ENV)
    if fork.returncode != 0:
        return False
    app = sh(["npx", "vitest", "run", *APP_SUITES.split()], cwd=APP, env=ENV)
    return app.returncode == 0


def _path_for(fname: str) -> Path:
    if fname in THEIRS:
        return FORK / fname
    if fname in APPS:
        return APP / fname
    return ROOT / fname


def main() -> int:
    only = {a.strip() for a in sys.argv[1:] if a.strip()}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — this is a spot check, "
              f"not a score for the stretch.")

    dirty = tracked_dirty()
    if dirty:
        print("Tracked files are modified. Commit or stash first — a harness that starts\n"
              "dirty cannot tell its own restore from your edits.\n" + "\n".join(dirty))
        return 2

    print("baseline… ", end="", flush=True)
    if not run_tests():
        print("RED. Nothing below would mean anything.")
        return 2
    print("green")

    survivors, faults = [], []
    for mid, fname, direction, why, edits in selected:
        path = _path_for(fname)
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            # ⛔⛔ COMPILED BEFORE IT IS WRITTEN, for the Python legs. A mis-indented
            # anchor still substring-matches and yields an unparseable file; the
            # suite then goes red on an import error and the mutant reports a kill
            # it never earned. TypeScript has no cheap equivalent here — `tsc` on
            # one file misses the project config — so the app mutants rely on vitest
            # failing loudly, which it does on a parse error.
            if fname.endswith(".py"):
                try:
                    compile(mutated, fname, "exec")
                except SyntaxError as syn:
                    raise AssertionError(
                        f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                        "check the anchor's indentation") from None
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            killed = not run_tests()
            flapped = False
            for _ in range(SURVIVOR_CONFIRMATIONS - 1):
                if killed:
                    break
                killed = not run_tests()
                flapped = flapped or killed
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = "  ⚠ FLAPPED — verdicts disagreed across runs" if flapped else ""
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed:
                survivors.append((mid, direction, why))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            faults.append((mid, direction, why, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")

    leftover = tracked_dirty()
    if leftover:
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant may still be in your source:\n"
              + "\n".join(leftover))
        return 3

    over = sum(1 for m in selected if m[2] == "over")
    label = " (SPOT CHECK — not the stretch's score)" if only else ""
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out "
              f"of the score above:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
