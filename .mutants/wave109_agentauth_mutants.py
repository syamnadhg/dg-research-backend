"""Wave 10.9 — can the tests see which host the agent's sign-in window opens on?

⛔⛔ WHAT THE WAVE CHANGED. The web app moved Firebase's `authDomain` to
superresearch.io, so Google's account picker names that site. The agent's local
sign-in page (`agent login --local`) still handed the SDK the project's
firebaseapp.com host, and the one test on the value checked only that it was
non-empty. The default moved, and the cost of moving it is now said out loud:
the window is served by the web app itself, so --local is no longer a way round
a superresearch.io outage, and every line that offers --local says so.

Every mutant below is a way the change could quietly come undone:

  C1  — ⛔⛔ the default goes back to firebaseapp.com. The defect itself.
  C2  — the environment stops being read. The default pin alone cannot see it;
        the override pin can.
  C3  — the config the page receives stops carrying the value.
  B1  — the bridge route overrides it on the way out. The config pins stay green;
        only the live GET /login/config can see it.
  L1  — the line spells the host instead of reading it, so a staging override
        makes it lie.
  L2-L5 — a line offering --local loses its caveat, or the helper says nothing.
  L6-L7 — the caveat escapes its branch and is printed after a timeout or an
        expired link, where no fallback was offered.
  L8  — the caveat is printed BEFORE the offer, where its "Its" points at nothing.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE — a mutant that does not parse fails every test
and would be scored as a kill. Both are harness faults, counted OUT.

⛔ THE AGENT IS A SECOND PACKAGE: its suite runs from `agent/` (its own
pyproject `testpaths`, and `python -m` puts `agent/` on sys.path so `import
facade` resolves to THIS tree), exactly as CI's "Run agent tests" step does.

  .venv/bin/python .mutants/wave109_agentauth_mutants.py
  .venv/bin/python .mutants/wave109_agentauth_mutants.py C1 B1
"""
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "agent"

SUITES = ("tests/test_signin_domain_0921.py "
          "tests/test_config.py "
          "tests/test_cli_commands.py "
          "tests/test_bridge_csrf.py")
CONFIG = "agent/facade/config.py"
CLI = "agent/facade/cli.py"
BRIDGE = "agent/facade/bridge.py"
FILES = (CONFIG, CLI, BRIDGE)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: the value ───────────────────────────────────────────────────────
A_DEFAULT = 'AUTH_DOMAIN: str = os.environ.get("SUPER_AGENT_AUTH_DOMAIN", "superresearch.io")'
A_SERVED = '        "authDomain": AUTH_DOMAIN,\n'
A_ROUTE = ("                cfg = config.web_config()\n"
           "                cfg[\"loginToken\"] = state.login_token\n")

# ── anchors: the lines that offer --local ────────────────────────────────────
L_HELPER = ('    return f"Its Google sign-in window opens on {config.AUTH_DOMAIN}, '
            'so that site must be up too."')
L_STEP = ('        b.dim("Web sign-in unreachable right now — host-local fallback:  '
          'agent login --local")\n'
          '        b.dim(_local_signin_needs())\n'
          '    else:\n'
          '        b.dim("Finish sign-in later:  /sr login  in chat  (or: agent login).")\n'
          '    return False\n')
L_STEP_OFFER = ('        b.dim("Web sign-in unreachable right now — host-local fallback:  '
                'agent login --local")\n')
L_REMOTE = ('        b.dim("Web sign-in unreachable — host-local fallback:  agent login --local")\n'
            '        b.dim(_local_signin_needs())\n'
            '    return 1\n')
L_REMOTE_OFFER = ('        b.dim("Web sign-in unreachable — host-local fallback:  '
                  'agent login --local")\n')
L_LOCAL = ('    b.dim("Sign in with your Super Research Google account (research-only).")\n'
           '    b.dim(_local_signin_needs())\n')

MUTANTS = [
    # ── the value ───────────────────────────────────────────────────────────
    ("C1", "under", CONFIG,
     "⛔⛔ THE DEFECT ITSELF — the default names the project's firebaseapp.com "
     "host again, and the picker on the local page says so",
     [(A_DEFAULT, 'AUTH_DOMAIN: str = os.environ.get("SUPER_AGENT_AUTH_DOMAIN", '
                  '"super-research-492814.firebaseapp.com")')]),

    ("C2", "over", CONFIG,
     "⛔ the staging override stops being read — the default pin cannot tell, "
     "because the default is still right",
     [(A_DEFAULT, 'AUTH_DOMAIN: str = "superresearch.io"')]),

    ("C3", "under", CONFIG,
     "⛔ the page's config stops carrying the value: the module constant is "
     "right and the SDK is handed something else",
     [(A_SERVED, '        "authDomain": f"{PROJECT_ID}.firebaseapp.com",\n')]),

    ("B1", "under", BRIDGE,
     "⛔⛔ THE CONSUMER — the bridge route rewrites the host on the way out. "
     "Every config pin stays green; only the live GET /login/config sees it",
     [(A_ROUTE, "                cfg = config.web_config()\n"
                "                cfg[\"authDomain\"] = config.PROJECT_ID + \".firebaseapp.com\"\n"
                "                cfg[\"loginToken\"] = state.login_token\n")]),

    # ── the lines that offer --local ───────────────────────────────────────
    ("L1", "under", CLI,
     "⛔ the caveat spells the host instead of reading it, so a staging "
     "override makes it name a site the window does not open on",
     [(L_HELPER, '    return "Its Google sign-in window opens on superresearch.io, '
                 'so that site must be up too."')]),

    ("L2", "under", CLI,
     "⛔ the helper says nothing: every call site still reads correctly and "
     "prints an empty line",
     [(L_HELPER, '    return ""')]),

    ("L3", "under", CLI,
     "⛔ `connect`'s sign-in step offers --local with no caveat again",
     [(L_STEP, L_STEP.replace("        b.dim(_local_signin_needs())\n", ""))]),

    ("L4", "under", CLI,
     "⛔ `agent login` offers --local with no caveat again",
     [(L_REMOTE, L_REMOTE.replace("        b.dim(_local_signin_needs())\n", ""))]),

    ("L5", "under", CLI,
     "⛔ `agent login --local` itself stops naming the host its window opens on",
     [(L_LOCAL, '    b.dim("Sign in with your Super Research Google account '
                '(research-only).")\n')]),

    ("L6", "over", CLI,
     "⛔ the caveat escapes the start-failed branch in `connect`: a timeout "
     "gets told what a fallback it was never offered depends on",
     [(L_STEP, L_STEP_OFFER
       + '    else:\n'
       + '        b.dim("Finish sign-in later:  /sr login  in chat  (or: agent login).")\n'
       + '    b.dim(_local_signin_needs())\n'
       + '    return False\n')]),

    ("L7", "over", CLI,
     "⛔ the caveat escapes the start-failed branch in `agent login`: an expired "
     "link gets it too",
     [(L_REMOTE, L_REMOTE_OFFER
       + '    b.dim(_local_signin_needs())\n'
       + '    return 1\n')]),

    ("L8", "under", CLI,
     "⚠ the caveat lands BEFORE the offer, where its \"Its\" refers to nothing "
     "the person has read yet",
     [(L_REMOTE, '        b.dim(_local_signin_needs())\n'
                 + L_REMOTE_OFFER
                 + '    return 1\n')]),
]


def _run(cmd):
    return subprocess.run(cmd, cwd=AGENT, env=ENV, shell=True,
                          capture_output=True, text=True)


def green():
    # ⭐ THE INTERPRETER RUNNING THIS FILE, so a worktree with no `.venv` of its
    # own still measures its own tree (pytest puts the cwd first on sys.path).
    r = _run(f"{shlex.quote(sys.executable)} -m pytest {SUITES} -q -p no:cacheprovider")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it. Read from the LAST
    # "… in N.NNs" line only, so a warning whose text says "error" cannot count.
    summary = ""
    for ln in (r.stdout or "").splitlines():
        m = re.match(r"^=*\s*(.+?) in [\d.]+s", ln.strip())
        if m:
            summary = m.group(1)
    return "passed" in summary and "failed" not in summary and "error" not in summary


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which EXECUTES
# it — so an unguarded runner would turn the sweep into a full mutation run.
if __name__ == "__main__":
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in FILES}

    def restore():
        for f, t in ORIGINALS.items():
            (ROOT / f).write_text(t, encoding="utf-8")

    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    if not green():
        print("⛔ BASELINE RED — fix the suite before mutating anything.")
        sys.exit(2)
    print("green\n")

    survivors = []
    selected = [m for m in MUTANTS if not only or m[0] in only]
    for mid, direction, fname, why, edits in selected:
        path = ROOT / fname
        original = ORIGINALS[fname]
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError(f"replacement identical to anchor: {frm[:70]!r}")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {fname} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to)
            # ⛔ A MUTANT THAT DOES NOT PARSE FAILS EVERY TEST and would be
            # scored as a kill. Refuse it before it reaches the disk.
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as se:
                raise AssertionError(f"mutant does not compile: {se}")
            path.write_text(mutated, encoding="utf-8")
            if green():
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}")
            else:
                print(f"  {mid}  ✓ killed")
        except AssertionError as e:
            survivors.append(f"{mid} (anchor)")
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}")
        finally:
            path.write_text(original, encoding="utf-8")

    restore()
    for f, t in ORIGINALS.items():
        if (ROOT / f).read_text(encoding="utf-8") != t:
            print(f"\n⛔⛔ RESTORE FAILED for {f} — fix the tree before trusting anything above")
            sys.exit(2)

    print(f"\n{len(selected) - len(survivors)}/{len(selected)} killed")
    if survivors:
        print("survivors: " + ", ".join(survivors))
        sys.exit(1)
    print("clean.\n")
