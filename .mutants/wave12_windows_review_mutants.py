"""Mutation harness — the Windows review of wave 12 (2026-09-28).

⛔⛔ WHAT THIS CODE DECIDES.
  H* — sr.py's hide and question guards: a request to KEEP a computer public, or a
       question about it, never hides it (and so never switches Allow all off).
  P* — a lone particle ("off") is never a computer's name.
  A* — approval words are the Allow-all setting, never a hide or an unlink.
  R* — a run named with Allow-all words answers to "stop / pause research on …".
  K* — "research computer" is a kind, not a name.
  S* — what the owner switch says: a lost reply cannot confirm; signed out is said
       the chat's way; the bridge's refusal names the switch asked about.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔⛔ AN IN-FLIGHT MARKER, because Windows kills without running `finally:` or a
SIGTERM handler: a run that dies leaves `<this file>.inflight` naming the file that
still holds a mutant, and the next run refuses to start until it is restored. Run
this in a throwaway worktree, never in the tree the agent is installed from.

  python .mutants/wave12_windows_review_mutants.py
  python .mutants/wave12_windows_review_mutants.py H1 S3
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

SR = "agent/facade/skill/scripts/sr.py"
BRIDGE = "agent/facade/bridge.py"

SUITES = {
    SR: (AGENT, "tests/test_allow_all_windows_review_0928.py"),
    BRIDGE: (AGENT, "tests/test_allow_all_bridge_0926.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    # ═══ H — keep-public requests and questions never hide ════════════════════
    ("H1", SR, "⛔⛔ 'stop hiding my mac' / 'don't take my mac off the public list' HIDE "
     "it, unconfirmed — and switch Allow all off",
     [("        if _hiding_kw and _stop_hiding:\n            return None, [_NL_CATCH_ALL]\n",
       "        if False:\n            return None, [_NL_CATCH_ALL]\n")]),
    ("H2", SR, "⛔ 'my mac shouldn't be private' / 'I don't want my mac private' hide it",
     [("            or re.search(r\"\\b(?:shouldn['’]?t|should\\s+not|don['’]?t\\s+want|do\\s+not\\s+want)\"\n"
       "                         rf\"\\b[^.?!]{{0,20}}\\b{_HIDE_POLARITY}\\b\",\n"
       "                         _NL_QUOTED_RE.sub(\" \", t).lower()))",
       "            )")]),
    ("H3", SR, "⛔⛔ 'why is my mac private?' — a question with a question mark — hides it",
     [("    _asking_state = ((t.rstrip().endswith(\"?\")\n                      or re.match(",
       "    _asking_state = ((False\n                      or re.match(")]),
    ("H4", SR, "⛔ 'why is my mac not public' / 'should I hide my mac' (no question mark) "
     "hide it — the question words are the old short list again",
     [("r\"which|how|why|when|will|has|have|should|if|\"\n",
       "r\"which|how|\"\n")]),

    # ═══ P — a particle is not a name ══════════════════════════════════════════
    ("P1", SR, "⛔⛔ 'turn off public for my mac' reads “off” as a computer and hides the "
     "Office PC",
     [("    if not w or re.fullmatch(r\"(?:off|on|up|down|out)\", w, re.I):\n",
       "    if not w:\n")]),

    ("P2", SR, "⛔⛔ `device-visibility public --allow-all \"Studio PC\"` is refused by "
     "Python 3.12's argparse — the WSL chat runtime — 'unrecognized arguments'",
     [("            args = (args[:i + 1] + [a for a in args[i + 1:] if a != \"--allow-all\"]\n"
       "                    + [\"--allow-all\"])\n",
       "            pass\n")]),

    # ═══ A — approval words ════════════════════════════════════════════════════
    ("A1", SR, "⛔ 'turn off approving for my mac' (Allow all ON) hides it",
     [("    + r\"|\\b(?:turn|switch)\\w*\\s+off\\s+(?:the\\s+)?approv\\w*\"\n",
       "")]),
    ("A2", SR, "⛔ 'remove approval for my mac' offers to UNLINK a computer called "
     "“approval for my mac”",
     [("    + r\"|\\b(?:disable|remove|drop|get\\s+rid\\s+of)\\s+(?:the\\s+)?approv\\w*\"\n",
       "")]),

    # ═══ R — a run named with Allow-all words ══════════════════════════════════
    ("R1", SR, "⛔ 'stop research on allow all' reaches the catch-all — the run of that "
     "name cannot be stopped from chat",
     [("\"\n                r\"|(?:research|run)\\s+(?:on|about|into|for|called|named)\\b)\"",
       ")\"")]),
    ("R2", SR, "⛔ 'stop research “allow all”' reads the device list — the quoted title "
     "after the run word is not a title",
     [("    r\"(?:\\s+(?:research|run)(?:\\s+(?:on|about|called|named))?)?\\s*$\", re.I)",
       "    r\"\\s*$\", re.I)")]),

    # ═══ K — the product's own noun ════════════════════════════════════════════
    ("K1", SR, "⛔ 'make my research computer private' looks for a computer CALLED "
     "“research computer”",
     [("_PRODUCT_KIND = re.compile(r\"^(?:super\\s*research|research|sr)\\s+\", re.I)",
       "_PRODUCT_KIND = re.compile(r\"(?!x)x\", re.I)")]),

    # ═══ S — what the owner switch says ════════════════════════════════════════
    ("S1", SR, "⛔⛔ a lost reply says the bridge 'isn't running on this machine yet' — "
     "the read timeout is not marked",
     [("        if isinstance(e, TimeoutError):\n            out[\"reason\"] = \"timeout\"\n",
       "")]),
    ("S2", SR, "⛔⛔ a lost reply on the owner switch is reported as a missing bridge",
     [("    if code == 0 and body.get(\"reason\") == \"timeout\":\n",
       "    if False:\n")]),
    ("S3", SR, "⛔ signed out, the owner switch relays the terminal's 'run /login'",
     [("        said = _signed_out_or(body.get(\"error\") or \"the app gave no reason\")\n",
       "        said = body.get(\"error\") or \"the app gave no reason\"\n")]),
    ("S4", SR, "⛔ signed out, the owner PICKER relays 'run /login'",
     [("        return None, [f\"✗ {_signed_out_or(body.get('error', code))}\"]\n"
       "    owned = [d for d in (body.get(\"devices\") or []) if d.get(\"owned\")]\n",
       "        return None, [f\"✗ {body.get('error', code)}\"]\n"
       "    owned = [d for d in (body.get(\"devices\") or []) if d.get(\"owned\")]\n")]),
    ("S5", SR, "⛔ signed out, a NAMED owner switch relays 'run /login'",
     [("        # ⛔ Signed out, \"run /login\" is the terminal's word (`_signed_out_or`).\n"
       "        return None, [f\"✗ {_signed_out_or(body.get('error', code))}\"]\n",
       "        return None, [f\"✗ {body.get('error', code)}\"]\n")]),
    ("S6", BRIDGE, "⛔ a sharer's 'turn off allow all' is refused about who can FIND it",
     [("                                     \"change who can join it\" if has_all\n"
       "                                     else \"change who can find it\")",
       "                                     \"change who can find it\")")]),
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
