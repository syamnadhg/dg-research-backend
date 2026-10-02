"""Mutation harness — a Phase-2 browser crash goes back into each agent's own chat (10-01).

⛔⛔ WHAT THIS CODE DECIDES (research.py).
  C*  the crash hands its chats to its own retry: only a Chrome death, only in
      Phase 2 (or before it, on a retry still carrying them), taken before the
      `finally` resets `_runtime`; the retry keeps carrying what it was handed
      until it deals with it; the first Phase-2 attempt spends them, no other
      attempt and no other call gets them; an agent in chat mode is not carried.
  R*  the retry's Phase 2 goes back into each chat first and sets up only the
      rest; an agent already kept, or with no chat, is never opened; an agent set
      up again (a relaunch, a hard retry) leaves its old chat; a Stop ends it.
  I*  a chat is this run's only on BOTH halves — its own id, and a first message
      holding what this run sent (the brief's head, or the line typed beside an
      attached brief); signed out, unopenable or unproven costs only that agent;
      a dead Chrome unwinds as a crash instead; Gemini is found again by the
      sidebar hunt, scoped to its id, never after a Stop; no address is logged.
  S*  what the round-robin is handed: finished/researching verified, a Gemini plan
      not yet started watched for its Start; the tile set running; the chat noted
      again for a second crash.
  N*  Phase 2 notes each chat as the brief goes in, and its tab; at the crash the
      tab's own chat wins (Gemini moves chat after the send), the noted address
      when the tab is off its chats; a chat that moves is followed; Phase 1's
      ChatGPT chat is never taken.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔ Run it in a throwaway worktree, never in the checkout the backend runs from.

  .venv/bin/python .mutants/crash_rejoin_1001_mutants.py
  .venv/bin/python .mutants/crash_rejoin_1001_mutants.py C1 R2
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

#: The tests the mutants are measured by (a name, never a path: the anchor sweep
#: reads any "*.py" string in a mutant's row as its target file).
SUITES = {RESEARCH: (ROOT, "tests/test_crash_rejoin_1001" + ".py")}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    # ── C: the crash carries its chats into its own retry ───────────────────
    ('C1', RESEARCH, '⛔⛔ the crash takes no chats — the retry sends the brief to all three again',
     [('            _p2_rejoin_next = _p2_chats_to_rejoin()\n',
       '            pass\n')]),
    ('C2', RESEARCH, '⛔ any failure in Phase 2 carries chats, not only a Chrome death',
     [('        if _captured_failure_kind == "browser_crash" and last_phase <= 2:\n',
       '        if last_phase <= 2:\n')]),
    ('C3', RESEARCH, '⛔ a Chrome death in any phase carries Phase-2 chats',
     [('        if _captured_failure_kind == "browser_crash" and last_phase <= 2:\n',
       '        if _captured_failure_kind == "browser_crash":\n')]),
    ('C4', RESEARCH, '⛔⛔ the retry is not handed the chats',
     [('                           _p2_rejoin=_p2_rejoin_next)\n',
       '                           _p2_rejoin=None)\n')]),
    ('C5', RESEARCH, '⛔ the snapshot of the chats comes back empty',
     [('    out = {}\n    for k, u in dict(_runtime.p2_chat_urls).items():\n',
       '    return {}\n    for k, u in dict(_runtime.p2_chat_urls).items():\n')]),
    ('C6', RESEARCH, '⛔⛔ the retry drops what it was handed before Phase 2',
     [('    _p2_rejoin_left = dict(_p2_rejoin or {})\n',
       '    _p2_rejoin_left = {}\n')]),
    ('C7', RESEARCH, '⛔⛔ the Phase-2 attempt does not pass the chats on',
     [('                                       enabled_agents=_launch, rejoin=_rejoin),\n',
       '                                       enabled_agents=_launch, rejoin=None),\n')]),
    ('C8', RESEARCH, "⛔ the chats are not spent — a person's Retry rejoins instead of re-running",
     [('    if left:\n        left.clear()\n    return taken\n',
       '    return taken\n')]),
    ('C9', RESEARCH, "⛔ the person's new input is ignored — old chats rejoined without it",
     [('    taken = {} if new_input else dict(left or {})\n',
       '    taken = dict(left or {})\n')]),
    ('C10', RESEARCH, "⛔ the attempt never says the person's input joined the brief",
     [('                                          new_input=bool(extra_ctx or fb2))\n',
       '                                          new_input=False)\n')]),
    ('C11', RESEARCH, '⛔⛔ the retry forgets what it was handed — a second crash before '
                      'the rejoin sends the brief to all three again',
     [('    _runtime.p2_chat_urls.update(_p2_rejoin or {})\n',
       '    pass\n')]),
    ('C12', RESEARCH, '⛔ a retry that crashes before its Phase 2 hands nothing on',
     [('        if _captured_failure_kind == "browser_crash" and last_phase <= 2:\n',
       '        if _captured_failure_kind == "browser_crash" and last_phase == 2:\n')]),
    ('C13', RESEARCH, '⛔ an agent in chat mode is rejoined as a Deep Research',
     [('        if isinstance(_mode, dict) and _mode.get("actual") == "chat":\n'
       '            continue\n',
       '')]),
    ('C14', RESEARCH, '⛔⛔ another statement in run_pipeline empties the carried chats',
     [('    _p2_rejoin_left = dict(_p2_rejoin or {})\n    _p2_rejoin_next = {}\n',
       '    _p2_rejoin_left = dict(_p2_rejoin or {})\n    _p2_rejoin_next = {}\n'
       '    _p2_rejoin_left.clear()\n')]),

    # ── R: the retry's Phase 2 ──────────────────────────────────────────────
    ('R1', RESEARCH, '⛔⛔ Phase 2 never goes back into a chat',
     [('    if rejoin:  # a Stop, before or during it, ends it (`_p2_rejoin_chats`)\n',
       '    if False:\n')]),
    # R2 (a Stop before Phase 2 did not stop the rejoin) is R13 now: the rejoin
    # loop checks Stop before every chat, the first one included.
    ('R3', RESEARCH, '⛔⛔ a rejoined agent is set up and sent the brief all the same',
     [('        enabled_agents = [a for a in _launch\n'
       '                          if _agent_display_name(a) not in rejoined]\n',
       '        enabled_agents = list(_launch)\n')]),
    ('R4', RESEARCH, '⛔⛔ the rejoined agents never reach the round-robin',
     [('    if rejoined:\n        agents.update(rejoined)\n',
       '    if False:\n        agents.update(rejoined)\n')]),
    ('R5', RESEARCH, '⛔ the plan rejoins agents this attempt would not launch (a kept one)',
     [('    for agent in launch or ():\n        key = str(agent).lower()\n'
       '        url = (carried or {}).get(key) or ""\n',
       '    for agent in (carried or {}):\n        key = str(agent).lower()\n'
       '        url = (carried or {}).get(key) or ""\n')]),
    ('R6', RESEARCH, '⛔ an address that is not a chat is opened as one',
     [('        if _p2_chat_id(key, url):\n            out[key] = url\n',
       '        if url:\n            out[key] = url\n')]),
    ('R7', RESEARCH, "⛔ Claude's chat id is never read",
     [('        m = _CLAUDE_CHAT_URL_RE.search((url or "").split("?", 1)[0])\n'
       '        return m.group(1) if m else ""\n',
       '        m = _CLAUDE_CHAT_URL_RE.search((url or "").split("?", 1)[0])\n'
       '        return ""\n')]),
    ('R8', RESEARCH, '⛔ an agent with no chat is skipped instead of set up',
     [('        rejoined = await _p2_rejoin_chats(\n'
       '            browser, _p2_rejoin_plan(rejoin, _launch), _launch, brief_text)\n',
       '        rejoined = await _p2_rejoin_chats(\n'
       '            browser, _p2_rejoin_plan(rejoin, _launch), _launch, brief_text)\n'
       '        _launch = [a for a in _launch if a in rejoin]\n')]),
    ('R9', RESEARCH, '⛔ an agent set up again keeps its old chat — a crash before its '
                     'new brief takes it back into the chat it was leaving',
     [('        _p2_forget_chat(str(_a).lower())\n',
       '        pass\n')]),
    ('R10', RESEARCH, '⛔ the agents rejoined are forgotten with the ones set up again',
     [('    for _a in (enabled_agents if enabled_agents is not None\n'
       '               else ("chatgpt", "gemini", "claude")):\n',
       '    for _a in ("chatgpt", "gemini", "claude"):\n')]),
    ('R11', RESEARCH, "⛔ a hard retry keeps the chat it is leaving",
     [('            _p2_forget_chat(_agent_key)\n',
       '            pass\n')]),
    ('R12', RESEARCH, "⛔ a hard retry's new chat is never noted",
     [('                _p2_note_chat(_agent_key, new_page)  # 10-01: a crash retry rejoins it\n',
       '                pass\n')]),
    ('R13', RESEARCH, '⛔ a Stop does not stop the rejoin — chats open after it, pressed '
                      'before Phase 2 or mid-rejoin',
     [('        if _controls.is_stop():\n            break  # no page actions after Stop (#737)\n',
       '')]),

    # ── I: the proof ────────────────────────────────────────────────────────
    ('I1', RESEARCH, '⛔⛔ a tab that landed on another chat is taken for ours',
     [('        if _p2_chat_id(platform, live) == want:\n',
       '        if True:\n')]),
    ('I2', RESEARCH, "⛔⛔ a chat holding someone else's message is taken for ours",
     [('            if _p2_turn_holds_our_send(await reader(page), brief_text):\n',
       '            if True:\n')]),
    ('I3', RESEARCH, '⛔⛔ an attached brief never proves a chat (the default mode)',
     [('    return conversation_holds_brief(\n'
       '        turn_text, brief_fingerprint(_P2_ATTACHED_BRIEF_ASK)) is True\n',
       '    return False\n')]),
    ('I4', RESEARCH, '⛔ a pasted brief never proves a chat',
     [('    if conversation_holds_brief(turn_text, brief_fingerprint(brief_text)) is True:\n'
       '        return True\n',
       '')]),
    ('I5', RESEARCH, '⛔ one read only — a first message that mounts late costs the agent',
     [('_P2_REJOIN_READS = 4\n', '_P2_REJOIN_READS = 1\n')]),
    ('I6', RESEARCH, '⛔ a signed-out chat is taken for ours',
     [('        await check_auth(page, platform)\n    except SessionExpiredError:\n'
       '        return await _give_up("signed out")\n',
       '        pass\n    except SessionExpiredError:\n'
       '        return await _give_up("signed out")\n')]),
    ('I7', RESEARCH, '⛔ a Gemini that lands on its home is never looked for',
     [('            try:\n                found, adopted = await _gemini_adopt_lost_conversation(\n',
       '            try:\n                raise RuntimeError("no hunt")\n'
       '                found, adopted = await _gemini_adopt_lost_conversation(\n')]),
    ('I8', RESEARCH, '⛔ the hunt refuses our own finished Gemini (the send-side verdict)',
     [('                    page, brief_text, name, post_start=True, lost_convo_id=want)\n',
       '                    page, brief_text, name, post_start=False, lost_convo_id=want)\n')]),
    ('I9', RESEARCH, '⛔⛔ a Gemini found on another chat is taken for ours',
     [('            ours = bool(adopted) and _p2_chat_id(platform, live) == want\n',
       '            ours = bool(adopted)\n')]),
    ('I10', RESEARCH, '⛔ the tab that could not be proven is left open',
     [('        log(f"[resume] {name}: {why} — starting it again", "WARN")\n'
       '        if page is not None:\n            try:\n                await page.close()\n',
       '        log(f"[resume] {name}: {why} — starting it again", "WARN")\n'
       '        if page is not None:\n            try:\n                pass\n')]),
    ('I11', RESEARCH, "⛔ Claude's chat is read with ChatGPT's reader",
     [('    reader = (read_chatgpt_first_user_message if platform == "chatgpt"\n'
       '              else _claude_first_user_message)\n',
       '    reader = read_chatgpt_first_user_message\n')]),
    ('I12', RESEARCH, "⛔ Claude's first message is read off the whole page",
     [("    \"(cap) => { const n = document.querySelector('[data-testid=\\\"user-message\\\"]');\"\n",
       "    \"(cap) => { const n = document.body;\"\n")]),
    ('I13', RESEARCH, '⛔ the empty home stays open beside the Gemini the hunt found',
     [('            if adopted and found is not page:\n                try:\n'
       '                    await page.close()\n',
       '            if adopted and found is not page:\n                try:\n'
       '                    pass\n')]),
    ('I14', RESEARCH, '⛔⛔ a Chrome that died mid-rejoin is taken for a chat that cannot '
                      'come back — agents set up on a dead browser, their chats forgotten',
     [('        if await _browser_context_is_dead(browser):\n'
       '            _runtime.last_failure_kind = "browser_crash"\n',
       '        if False:\n'
       '            _runtime.last_failure_kind = "browser_crash"\n')]),
    ('I15', RESEARCH, '⛔ the sidebar hunt still clicks through Gemini after a Stop',
     [('        if not ours and not _controls.is_stop():\n',
       '        if not ours:\n')]),
    ('I16', RESEARCH, "⛔ a chat that would not open logs the error's address into run.log",
     [('        return await _give_up(f"its chat would not open ({type(e).__name__})")\n',
       '        return await _give_up(f"its chat would not open ({e})")\n')]),
    ('I17', RESEARCH, "⛔ the sidebar hunt's error puts its address into run.log",
     [('                log(f"[resume] {name}: the sidebar hunt raised ({type(e).__name__})",\n',
       '                log(f"[resume] {name}: the sidebar hunt raised ({e})",\n')]),

    # ── S: what the round-robin is handed ───────────────────────────────────
    ('S1', RESEARCH, '⛔ a Gemini plan not yet started is called running',
     [('    entry = {"page": page, "verified": state != "plan", "url": live,\n',
       '    entry = {"page": page, "verified": True, "url": live,\n')]),
    ('S2', RESEARCH, "⛔⛔ nobody presses a rejoined Gemini's Start research",
     [('        entry["gemini_watch_start"] = state == "plan"\n',
       '        entry["gemini_watch_start"] = False\n')]),
    ('S3', RESEARCH, '⛔ a Gemini already researching is watched for a Start',
     [('        entry["gemini_watch_start"] = state == "plan"\n',
       '        entry["gemini_watch_start"] = True\n')]),
    ('S4', RESEARCH, '⛔ a finished ChatGPT or Claude is logged as still researching',
     [('    return "finished" if done else "researching"\n',
       '    return "researching"\n')]),
    ('S5', RESEARCH, '⛔⛔ a rejoined chat is not noted — a second crash sends the brief again',
     [('    log(f"[resume] {name}: back on its own chat — {_log_words}")\n'
       '    _p2_note_chat(platform, page)\n',
       '    log(f"[resume] {name}: back on its own chat — {_log_words}")\n')]),
    ('S6', RESEARCH, "⛔ a rejoined agent's tile stays on errored",
     [('        _write_agent_terminal_status(platform, "running", force=True)\n'
       '    except Exception:\n        pass\n    emit_event("agent_progress", phase=2, agent=platform,',
       '        pass\n'
       '    except Exception:\n        pass\n    emit_event("agent_progress", phase=2, agent=platform,')]),
    ('S7', RESEARCH, "⛔ a rejoined Gemini loses the brief its stale-reload prover needs",
     [('        entry["brief"] = brief_text\n',
       '        entry["brief"] = ""\n')]),
    ('S8', RESEARCH, '⛔ a finished Gemini is logged as still researching',
     [('        if (await _gemini_done_read(page))[0]:\n            return "finished"\n',
       '        if False:\n            return "finished"\n')]),
    ('S9', RESEARCH, '⛔ a Gemini researching is read as a plan',
     [('        return "researching" if await _gemini_research_started(page) else "plan"\n',
       '        return "plan"\n')]),

    # ── N: the notes ────────────────────────────────────────────────────────
    ('N1', RESEARCH, '⛔ a verified ChatGPT is not noted',
     [('            _p2_note_chat("chatgpt", chatgpt_page)  # 10-01: a crash retry rejoins it\n',
       '')]),
    ('N2', RESEARCH, "⛔ a ChatGPT handed on at its own chat is not noted",
     [('                _p2_note_chat("chatgpt", chatgpt_page)  # 10-01, as above\n',
       '')]),
    ('N3', RESEARCH, '⛔ a verified Claude is not noted',
     [('            _p2_note_chat("claude", claude_page)  # 10-01: a crash retry rejoins it\n',
       '')]),
    ('N4', RESEARCH, "⛔ a Claude handed on at its own chat is not noted",
     [('                _p2_note_chat("claude", claude_page)  # 10-01, as above\n',
       '')]),
    ('N5', RESEARCH, '⛔ a Gemini sent its brief is not noted',
     [('            _p2_note_chat("gemini", gemini_page)  # 10-01: a crash retry rejoins it\n',
       '')]),
    ('N6', RESEARCH, '⛔ a chat that moves is not followed',
     [('            self.p2_chat_urls[platform] = self.agent_chat_urls[platform]\n',
       '            pass\n')]),
    ('N7', RESEARCH, "⛔⛔ Phase 1's ChatGPT chat is taken for Phase 2's",
     [('        if platform in self.p2_chat_urls and self.agent_chat_urls.get(platform):\n',
       '        if self.agent_chat_urls.get(platform):\n')]),
    ('N8', RESEARCH, '⛔ the typed line loses the space after its first sentence',
     [('        _P2_ATTACHED_BRIEF_ASK + " "\n',
       '        _P2_ATTACHED_BRIEF_ASK + ""\n')]),
    # Re-anchored 10-02 (review): only Gemini follows its tab now.
    ('N9', RESEARCH, "⛔⛔ the chat noted at the send is carried after Gemini's tab moved on "
                     "to the chat holding its plan",
     [('            pick = live if _p2_chat_id(k, live) else u\n',
       '            pick = u\n')]),
    ('N10', RESEARCH, '⛔ a tab off its chats (a home page) is carried instead of the chat',
     [('            pick = live if _p2_chat_id(k, live) else u\n',
       '            pick = live or u\n')]),
    ('N11', RESEARCH, '⛔ the tab is not kept beside the chat noted at the send',
     [('        _runtime.p2_chat_pages[platform] = page\n',
       '        pass\n')]),
    ('N12', RESEARCH, '⛔ a tab registered in place of the noted one is not followed — the '
                      'old tab wins at the crash',
     [('            if page is not None:\n                self.p2_chat_pages[platform] = page\n',
       '            if False:\n                self.p2_chat_pages[platform] = page\n')]),
]

#: ⛔ A MUTANT THAT HANGS IS A FAULT, NOT A KILL.
_RUN_TIMEOUT_S = 600


def green(cwd, suites):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *suites.split(), "-q", "-p", "no:cacheprovider"],
            cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"the suite ran past {_RUN_TIMEOUT_S}s — a hang, not a kill")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE; an ERROR is red too, and a
    # skipped test is not a measurement.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — an unguarded runner turns a seconds-long check into a full run.
if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if _INFLIGHT.exists():
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n    "
              f"{_INFLIGHT.read_text(encoding='utf-8').strip()}\nRestore that file "
              f"(git checkout -- <file>), then delete\n    {_INFLIGHT}")
        sys.exit(2)
    files = sorted({m[1] for m in MUTANTS})
    ORIGINALS = {f: (ROOT / f).read_bytes() for f in files}
    DIGESTS = {f: _digest(b) for f, b in ORIGINALS.items()}
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

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
            _INFLIGHT.write_text(f"{mid}\t{fname}\n", encoding="utf-8")
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
            if _digest(path.read_bytes()) == DIGESTS[fname]:
                try:
                    _INFLIGHT.unlink()
                except FileNotFoundError:
                    pass

    for f in files:
        if _digest((ROOT / f).read_bytes()) != DIGESTS[f]:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
