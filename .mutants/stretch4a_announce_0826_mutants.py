"""Mutation harness for stretch 4A — the sign-in announce.

⛔ WHAT THIS CODE DECIDES. Whether the one message a person gets after signing in
survives the process that minted it, says what actually happened, and cannot be
handed to the wrong account or stolen by the wrong chat.

⭐⭐ THE SHARPEST MUTANTS HERE:
  D3      — the uid check on the parked announce goes. Signing in as B is then
            handed A's email and A's research topic. Nothing on disk was
            account-scoped before this stretch, because nothing was on disk.
  D6/D8   — the two clearing points that were MISSING when this started.
            `clear_session_if` is the real sign-out path (`set_session(None)` has
            no non-test callers) and `_login_callback` is the `--local` page. With
            both gone, a revoke followed by a local re-login announced "Starting
            <the old topic> on <the old device> now" for a run that no longer
            existed. D8 is the one that shipped.
  D7      — the OPPOSITE over-correction: clearing on a compare-and-swap MISS,
            which destroys the announce belonging to the session a reconnect just
            swapped in. The CAS exists precisely to not touch that session.
  P1      — the sole-ONLINE rung goes. This is the whole reason "choose your
            device never arrives": firing a research has always routed to the one
            awake machine, while signing in with that same research pending gave
            up and said "reply yes". Most multi-device accounts are that shape.
  F1/F2   — the fourth outcome collapses back into `{}` (F1) or swallows errors
            into it (F2). F1 restores a guard that CANNOT FIRE: "you have three
            computers, pick one" and "Firestore threw" were the same value.
  F7      — the two "which computer?" asks drift into different wordings. The
            watchdog imports nothing from sr.py, so nothing but one test stops a
            person being asked the same question in two voices.
  T1      — a second chat steals the first chat's research again: both the topic
            and the DESTINATION were overwritten, so chat A's watchdog waited
            forever on a run that had been silently replaced. Two 200s, one lost
            request, no error anywhere.
  O1      — the cursor is committed before the announce is spoken. The shape
            FORK.md §4.2 already records as learned the hard way.
  C1      — the fork's claim call discards the reply again, throwing away what the
            bridge DID about the pending research while still suppressing the
            watcher. The person keeps the news they already had.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT of the score.

⚠ ONE MUTANT WAS DELIBERATELY NOT WRITTEN. Removing the conftest fixture that
stops the suite reading the developer's own Keychain would go RED on this machine
(the owner is signed in) and GREEN in CI (no keyring backend, no session) — a
mutant whose verdict depends on who runs it measures the machine, not the tests.
That asymmetry is the defect the fixture fixes; it cannot also be its own mutant.

⚠ TWO SUITES, AND BOTH MUST BE GREEN FOR A MUTANT TO COUNT AS SURVIVING. The
bridge and its watchdog are in the agent package; the fourth client is the fork,
which has its own virtualenv. A harness that ran one leg would report every
mutant in the other as killed.

    .venv/bin/python .mutants/stretch4a_announce_0826_mutants.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORK = ROOT.parent / "dg-hermes-fleet"

# The agent leg. `test_bridge_device.py` is in on purpose: it holds the
# origin-scope guard this stretch deliberately did NOT change, so a mutant that
# "fixes" the scope predicate is caught rather than reported as an improvement.
AGENT_SUITES = ("tests/test_signin_announce_0826.py "
                "tests/test_remote_autopoll.py "
                "tests/test_sr_stream.py "
                "tests/test_bridge_device.py "
                "tests/test_agent_session.py "
                "tests/test_store.py")

FORK_SUITES = "skills/tests/test_super_research_skill.py"

BRIDGE = "agent/facade/bridge.py"
PREFS = "agent/facade/prefs.py"
POLL = "agent/facade/skill/scripts/sr_attention_poll.py"
OURS = (BRIDGE, PREFS, POLL)

# ⚠ RELATIVE TO THE FORK, not to this repo.
FORK_SR = "skills/super-research/scripts/sr.py"
FORK_POLL = "skills/super-research/scripts/sr_attention_poll.py"
THEIRS = (FORK_SR, FORK_POLL)

SURVIVOR_CONFIRMATIONS = 2

ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# (id, file, direction, why, [(from, to), ...])
MUTANTS = [
    # ═══════════ D — durable, uid-bound, and cleared in one place ═══════════
    ("D1", BRIDGE, "under",
     "⛔ the announce stops being parked at all, so it lives only in process "
     "memory again and any restart between the sign-in and the next tick loses "
     "it — the asymmetry with run completions, which are re-derived every tick",
     [("                prefs.set_pending_announce(event, uid)",
       "                pass")]),
    ("D2", BRIDGE, "under",
     "the read stops falling back to disk, so the parked copy exists and is "
     "never consulted: written, never returned",
     [("            ev = prefs.get_pending_announce(uid)",
       "            ev = None")]),
    ("D3", PREFS, "over",
     "⛔⛔ THE UID CHECK GOES. Signing in as B is handed A's email and A's "
     "research topic — a cross-account leak that could not exist before this "
     "stretch only because nothing was on disk to leak",
     [("    if isinstance(ev, dict) and ev and owner and owner == uid:",
       "    if isinstance(ev, dict) and ev:")]),
    ("D4", PREFS, "under",
     "the clear pops the announce and leaves the uid key, so the file says an "
     "announce belongs to an account while carrying no announce",
     [('        popped = [prefs.pop(k, None) for k in (_PENDING_ANNOUNCE, _PENDING_ANNOUNCE_UID)]',
       '        popped = [prefs.pop(_PENDING_ANNOUNCE, None)]')]),
    ("D5", BRIDGE, "under",
     "⛔ the clear stops reaching the disk, so the next peek rehydrates the "
     "announce from the parked copy — it comes back from the dead",
     [("            prefs.clear_pending_announce()\n        except Exception as e:  # noqa: BLE001\n            log.warning(\"could not clear the parked sign-in announce (%s)\",\n                        type(e).__name__)",
       "            pass\n        except Exception as e:  # noqa: BLE001\n            log.warning(\"could not clear the parked sign-in announce (%s)\",\n                        type(e).__name__)")]),
    ("D6", BRIDGE, "under",
     "⛔⛔ THE REAL SIGN-OUT PATH STOPS CLEARING. `_self_logout` reaches "
     "`clear_session_if`, never `set_session(None)` — which has no non-test "
     "callers — so a /logout or an app Revoke leaves the announce alive",
     [("        if cleared:\n            # ⛔ THE REAL SIGN-OUT PATH.",
       "        if False:\n            # ⛔ THE REAL SIGN-OUT PATH.")]),
    ("D7", BRIDGE, "over",
     "⛔ THE OPPOSITE ERROR: it clears on a compare-and-swap MISS too, "
     "destroying the announce of the session a concurrent reconnect just swapped "
     "in — the exact session the CAS exists to protect",
     [("        if cleared:\n            # ⛔ THE REAL SIGN-OUT PATH.",
       "        if True:\n            # ⛔ THE REAL SIGN-OUT PATH.")]),
    ("D8", BRIDGE, "under",
     "⛔⛔ THE ONE THAT SHIPPED. The host-local login page stops clearing, so a "
     "revoke followed by `agent login --local` hands the chat the PREVIOUS "
     "session's announce: \"Starting <the old topic> on <the old device> now\"",
     [("            state.clear_signed_in()\n            state.rotate_login_token()",
       "            state.rotate_login_token()")]),
    ("D9", PREFS, "over",
     "⛔⛔ AN EMPTY UID MATCHES AN EMPTY UID. A truncated write or a hand-edited "
     "file leaves `pendingAnnounceUid: \"\"`, and then the announce is readable by "
     "whoever asks with nothing — the same cross-account leak the binding exists "
     "to prevent. ⭐ RE-POINTED 2026-08-26: the first version of this mutant "
     "SURVIVED, which is how the hole was found; closing it changed the line the "
     "anchor named, so the next run reported a harness fault rather than a kill",
     [("    if isinstance(ev, dict) and ev and owner and owner == uid:",
       "    if isinstance(ev, dict) and ev and owner == uid:")]),
    ("D10", BRIDGE, "over",
     "⛔ the park stops being best-effort, so a read-only disk takes the SIGN-IN "
     "down with it — a courtesy message failing the thing it is a courtesy about",
     [("        except Exception as e:  # noqa: BLE001 — an announce must never fail a sign-in\n            log.warning(\"could not park the sign-in announce (%s) — memory only\",\n                        type(e).__name__)",
       "        except Exception:  # noqa: BLE001\n            raise")]),
    ("D11", BRIDGE, "over",
     "⛔ delivery goes back to at-most-once: the read consumes as it reads, so "
     "any failure afterwards destroys the announce — and a scope that does not "
     "own the event silently eats it",
     [("        with self._lock:\n            ev = self._signed_in\n        if isinstance(ev, dict):\n            return ev if ev.get(\"uid\") in (None, uid) else None",
       "        with self._lock:\n            ev = self._signed_in\n            self._signed_in = None\n        if isinstance(ev, dict):\n            return ev if ev.get(\"uid\") in (None, uid) else None")]),
    ("D12", BRIDGE, "under",
     "the delivered announce is never cleared, so every later tick re-announces "
     "the same sign-in — at-least-once with nothing to bound it on this side",
     [("                        # Delivered — now drop it, from memory and from disk.\n                        state.clear_signed_in()",
       "                        pass")]),

    # ═══════════ P — one device decision, shared by two consumers ═══════════
    ("P1", BRIDGE, "under",
     "⛔⛔ THE SOLE-ONLINE RUNG GOES, which is the whole defect: firing a "
     "research routes to the one awake machine while signing in with that same "
     "research pending gives up and says \"reply yes\". Most multi-device "
     "accounts are exactly that shape",
     [("    online = [d for d in devs if _device_is_online(d) and d.get(\"id\")]\n    if len(online) == 1:\n        return online[0].get(\"id\"), \"\", stale",
       "    online = [d for d in devs if _device_is_online(d) and d.get(\"id\")]")]),
    ("P2", BRIDGE, "under",
     "the stale flag is never raised, so a selection pointing at a removed "
     "device is re-derived by every later sign-in and every later run",
     [("    stale = bool(selected)", "    stale = False")]),
    ("P3", BRIDGE, "over",
     "a sole device with no id is returned anyway, so the run is enqueued to an "
     "empty string instead of falling through to the ask",
     [("        did = devs[0].get(\"id\")\n        if did:\n            return did, \"\", stale",
       "        return devs[0].get(\"id\"), \"\", stale")]),
    ("P4", BRIDGE, "over",
     "⛔ the two asks collapse into one reason, so somebody whose last computer "
     "became unreachable is told only \"pick one\" and never why they are being "
     "asked — the collision an earlier wave already fixed once",
     [('    return None, ("stale_selection" if stale else "no_selection"), stale',
       '    return None, "no_selection", stale')]),
    ("P5", BRIDGE, "over",
     "the online window is widened to half an hour, so a machine that went to "
     "sleep twenty minutes ago is auto-picked and the run is enqueued to nothing",
     [("_DEVICE_ONLINE_MS = 30_000", "_DEVICE_ONLINE_MS = 30 * 60_000")]),
    ("P6", BRIDGE, "under",
     "the ambiguous case hands back no descriptors, so the announce knows a "
     "choice is needed and cannot name a single computer to choose between",
     [("    return None, None, [_device_descriptor(d) for d in devs]",
       "    return None, None, []")]),
    ("P7", BRIDGE, "over",
     "⛔ the whole device document goes into the announce instead of the "
     "descriptor — heartbeat internals and owner uids into a chat payload",
     [("    return None, None, [_device_descriptor(d) for d in devs]",
       "    return None, None, list(devs)")]),
    ("P8", BRIDGE, "under",
     "the sign-in path stops dropping the dead selection even though it now "
     "knows it is dead: the check runs, costs its read, and decides nothing",
     [("    if stale:\n        # The saved selection is no longer a member — drop it here too, exactly as\n        # the run path does, or every later sign-in re-derives the same dead pick.\n        prefs.clear_selected_device()",
       "    if False:\n        prefs.clear_selected_device()")]),

    # ═══════════ F — the fourth outcome, through four surfaces ══════════════
    ("F1", BRIDGE, "under",
     "⛔⛔ THE FOURTH OUTCOME COLLAPSES BACK INTO AN EMPTY DICT, restoring a "
     "guard that CANNOT FIRE: \"you have three computers\" and \"Firestore "
     "threw\" become the same value, and the comment says \"let the chat "
     "choose\" while naming nothing to choose between",
     [('            return {"needsDeviceChoice": True, "topic": topic, "devices": choices}',
       '            return {}')]),
    ("F2", BRIDGE, "over",
     "⛔ the ERROR path claims the fourth outcome too, so a Firestore failure "
     "tells somebody their account has several computers to pick from — a lie "
     "with a device list attached",
     [('        log.warning("sign-in auto-start failed (%s) — falling back to confirm-then-run",\n                    type(e).__name__)\n        return {}',
       '        log.warning("sign-in auto-start failed (%s) — falling back to confirm-then-run",\n                    type(e).__name__)\n        return {"needsDeviceChoice": True, "topic": topic, "devices": []}')]),
    ("F3", BRIDGE, "under",
     "the flag never crosses the wire, so every client falls back to \"reply "
     "yes\" no matter what the bridge decided",
     [('                            "needsDeviceChoice": bool(ev.get("needsDeviceChoice")),',
       '                            "needsDeviceChoice": False,')]),
    ("F4", BRIDGE, "under",
     "the devices never cross the wire, so the ask arrives with nothing to name",
     [('                            "devices": ev.get("devices") or [],',
       '                            "devices": [],')]),
    ("F5", BRIDGE, "over",
     "⛔ the \"reply yes\" offer rides along WITH the pick-one ask, so the "
     "person is asked two different questions in one breath and can answer the "
     "wrong one",
     [('    ev["pendingTopic"] = "" if (result.get("autoStarted") or result.get("needsDevice")\n                                or result.get("needsDeviceChoice")) else topic',
       '    ev["pendingTopic"] = "" if (result.get("autoStarted") or result.get("needsDevice")) else topic')]),
    ("F6", POLL, "under",
     "the watchdog's picker branch goes, so the ask falls through to \"Continue "
     "with X? Reply yes\" — an offer whose obstacle was never consent",
     [('    if signed_in.get("needsDeviceChoice"):',
       '    if False:')]),
    ("F7", POLL, "over",
     "⛔⛔ THE TWO ASKS DRIFT INTO DIFFERENT WORDINGS. sr.py asks this when a "
     "fired research cannot be routed; the watchdog asks it after a sign-in. "
     "The scripts share no module, so one question becomes two voices",
     [('                f"You have {len(devs)} research computers — which should run "\n                f"{quoted}?")',
       '                f"Which of your {len(devs)} computers should handle "\n                f"{quoted}?")')]),
    ("F8", POLL, "under",
     "the online marks go, so a list of five computers gives no clue which one "
     "is actually awake to run the work",
     [('            dot = " · online" if online is True else (" · offline" if online is False else "")',
       '            dot = ""')]),
    ("F9", POLL, "over",
     "the empty-list guard goes, so an older bridge's bare flag renders \"You "
     "have 0 research computers\" and invites the person to use a machine called "
     "\"that computer\"",
     [('        if not devs:\n            return (f"✓ Signed in as {who}.\\n\\n"\n                    f"Tell me to start {quoted} and I\'ll ask which computer to use.")',
       '        if False:\n            pass')]),
    ("F10", POLL, "under",
     "the watchdog's name fallback loses the hostname rung, so a machine with no "
     "friendly name is called by its raw id here and by its hostname in sr.py",
     [('    return d.get("name") or d.get("hostname") or d.get("id") or "your Research Computer"',
       '    return d.get("name") or d.get("id") or "your Research Computer"')]),
    ("F11", FORK_POLL, "under",
     "⛔ the fourth client loses the picker and goes back to \"say go ahead\" — "
     "asking for permission when what is missing is not permission",
     [('    elif signed.get("needsDeviceChoice"):', '    elif False:')]),
    ("F12", FORK_POLL, "over",
     "⛔ the picker is tested BEFORE the started case, so a research that IS "
     "running is reported as waiting for somebody to choose a computer",
     [('    if signed.get("autoStarted"):', '    if signed.get("needsDeviceChoice"):')]),
    ("F13", FORK_POLL, "under",
     "the fourth client renders an empty list of computers and then asks which "
     "of them to use",
     [('        first = sanitize(str((devs[0].get("name") if devs else "") or "that one"))[:80]',
       '        first = "that one"')]),

    # ═══════════ O — speak before committing the cursor ═════════════════════
    ("O1", POLL, "under",
     "⛔⛔ back to committing the cursor before speaking. A tick that dies "
     "between the two leaves a state file claiming the announce was delivered "
     "and no announce anywhere — and the bridge has already handed it over",
     [('    if out:\n        print("\\n".join(out))\n    _save_state(new_state, state_file)',
       '    _save_state(new_state, state_file)\n    if out:\n        print("\\n".join(out))')]),

    # ═══════════ T — a second chat may not take the first one's research ════
    ("T1", BRIDGE, "under",
     "⛔⛔ THE THEFT RETURNS. Chat A's topic AND destination are overwritten by "
     "chat B's post, so after sign-in only B's research runs and A's watchdog — "
     "armed, and told \"I'll pick this up\" — waits forever. Two 200s, one lost "
     "request, no error anywhere",
     [('                if ((flow.pending_topic or "").strip()\n                        and isinstance(origin, dict) and isinstance(flow.origin, dict)\n                        and not _same_origin(flow.origin, origin)):',
       '                if False:')]),
    ("T2", BRIDGE, "over",
     "⛔ the same chat is refused too, so a person correcting their own topic in "
     "the same conversation is told somebody else has claimed the sign-in",
     [('                        and not _same_origin(flow.origin, origin)):',
       '                        and True):')]),
    ("T3", BRIDGE, "over",
     "the refusal fires when NO topic is held, so the ordinary first attach — "
     "the one that gives a terminal sign-in a chat to answer in — is rejected",
     [('                if ((flow.pending_topic or "").strip()\n                        and isinstance(origin, dict)',
       '                if (isinstance(origin, dict)')]),
    ("T4", BRIDGE, "under",
     "the platform stops counting, so telegram chat 111 and whatsapp chat 111 "
     "read as one conversation and one steals the other's research",
     [('    return (ca["platform"].lower() == cb["platform"].lower()\n            and ca["chat_id"] == cb["chat_id"])',
       '    return ca["chat_id"] == cb["chat_id"]')]),
    ("T5", BRIDGE, "over",
     "the thread is compared too, so a reply inside a thread reads as a "
     "different chat and is refused — while `/updates` scoping still delivers to "
     "it, which is the worst of both",
     [('    return (ca["platform"].lower() == cb["platform"].lower()\n            and ca["chat_id"] == cb["chat_id"])',
       '    return ca == cb')]),
    ("T6", BRIDGE, "over",
     "two unusable origins count as the same conversation, so a malformed origin "
     "silently inherits whatever the flow was already carrying",
     [("    if ca is None or cb is None:\n        return False",
       "    if ca is None or cb is None:\n        return ca is cb")]),

    # ═══════════ C — the fork's login-done ═════════════════════════════════
    ("C1", FORK_SR, "under",
     "⛔⛔ the claim call discards the reply again. It still stops the watcher "
     "repeating, so nothing looks broken — but what the program DID about the "
     "pending research is thrown away and the person keeps only the news they "
     "already had",
     [("    note = body.get(\"signedIn\")\n    return note if isinstance(note, dict) else {}",
       "    return {}")]),
    ("C2", FORK_SR, "under",
     "the outcome is never said, so login-done falls back to telling the "
     "assistant to go and look at something the note had already answered",
     [("            for line in _signed_in_outcome_lines(note):\n                _say(line)",
       "            pass")]),
    ("C3", FORK_SR, "over",
     "⛔ the outcome lines are rendered with no note at all, so an unknown "
     "outcome is reported as a concrete one — invented news",
     [("        if note:\n            # ⭐ SAY WHAT HAPPENED", "        if True:\n            # ⭐ SAY WHAT HAPPENED")]),
    ("C4", FORK_SR, "under",
     "the claim goes entirely, so the watcher repeats the sign-in a few minutes "
     "later — the duplicate this whole flow exists to avoid",
     [("    note = _claim_signed_in_announce()", "    note = {}")]),
    ("C5", FORK_SR, "over",
     "a plain sign-in with nothing pending gets an invented waiting-research "
     "line, so somebody who asked for nothing is told to say go ahead",
     [('    if topic:\n        return ["They asked for %s before signing in and it is waiting on a yes. "\n                "Offer to start it." % named]\n    return []',
       '    return ["They asked for %s before signing in and it is waiting on a yes. "\n            "Offer to start it." % named]')]),
]


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def tracked_dirty() -> list[str]:
    out = sh(["git", "status", "--porcelain", "--", *OURS, "agent/tests"],
             cwd=ROOT).stdout
    ours = [f"[be] {ln}" for ln in out.splitlines() if ln and not ln.startswith("?? ")]
    out2 = sh(["git", "status", "--porcelain", "--", *THEIRS,
               "skills/tests"], cwd=FORK).stdout
    theirs = [f"[fork] {ln}" for ln in out2.splitlines() if ln and not ln.startswith("?? ")]
    return ours + theirs


def run_tests() -> bool:
    """Both legs, and both must pass.

    ⛔ The agent package and the fork are separate programs with separate
    rootdirs, and the fork has its own virtualenv because its suite imports
    modules this repo does not have. A harness that ran one leg would report
    every mutant in the other as killed.

    ⛔⛔ AND THE FORK LEG DEMANDS A CLEAN EXIT WITH NO TOLERANCE. The fork's
    `skills/tests` DIRECTORY carries pre-existing failures, so an earlier harness
    in this repo allowed a budget — and because the leg runs ONE FILE, which is
    clean, that budget silently absorbed the first real kills and reported every
    fork mutant as a survivor. A tolerance is only meaningful against the same
    selection it was measured on."""
    purge_pycache(ROOT)
    agent_env = {**ENV, "PYTHONPATH": str(ROOT / "agent")}
    agent = sh([sys.executable, "-B", "-m", "pytest", *AGENT_SUITES.split(),
                "-q", "-p", "no:cacheprovider"],
               cwd=ROOT / "agent", env=agent_env)
    if agent.returncode != 0:
        return False
    purge_pycache(FORK)
    fork_py = FORK / ".venv" / "bin" / "python"
    if not fork_py.exists():
        raise AssertionError(
            f"the fork's virtualenv is missing at {fork_py} — this harness cannot "
            "measure the fourth client without it, and skipping that leg would "
            "report every fork mutant as killed")
    fork = sh([str(fork_py), "-B", "-m", "pytest", FORK_SUITES,
               "-q", "-p", "no:cacheprovider"], cwd=FORK, env=ENV)
    return fork.returncode == 0


def _path_for(fname: str) -> Path:
    return (FORK / fname) if fname in THEIRS else (ROOT / fname)


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
            # ⛔⛔ COMPILED BEFORE IT IS WRITTEN. A mis-indented anchor still
            # substring-matches and yields an unparseable file; the suite then goes
            # red on an import error and the mutant reports a kill it never earned.
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
            # ⛔⛔ A HARNESS FAULT IS NOT A SURVIVOR. A stale anchor or a mutant
            # that does not parse MEASURED NOTHING — it never reached the file, so
            # the suite was never asked. Filing it under survivors reads as "the
            # tests have a gap", which sends you to write an assertion for a defect
            # that was never tested.
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
        # ⛔ Counted OUT of the score: a mutant that never reached the file tells
        # you nothing about the suite either way, so folding it into the
        # denominator would understate coverage as surely as folding it into the
        # numerator would overstate it.
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
