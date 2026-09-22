"""Wave 10.9 — does anything measure the Windows port probe and the wheel stamp?

⛔⛔ WHAT THE WAVE CLOSED.

  OPS-7 — the Windows branch of `_listening_pids` (netstat) had never run on
          any machine: every test drove "Linux" or "Unsupported". Its parse is
          now `_netstat_listening_pids`, pure, and driven through the real
          probe with a netstat stand-in.
  NEW-2 — that parse kept a row only if it said "LISTENING" in English.
          netstat translates the state column, so a German Windows matched no
          row and still reported that the probe RAN: a held port read as free.
          A French one never got that far — "ÉCOUTE" is 0x90 in cp850,
          undefined in cp1252, so the strict decode raised and the probe read
          as "could not look". Rows are now listeners by their foreign address,
          the decode replaces, and `-p TCP` (IPv4 only) is gone so an IPv6-only
          listener is seen at all.
  OPS-5 — nothing could say which code a published wheel held. The build now
          stamps `_sr_build.json` (a CRLF-blind fingerprint of the first-party
          sources, plus commit/dirty hints) BEFORE compiling, and
          tools/check_release.py refuses a release whose wheels disagree or
          carry no stamp.

The quiet mutants matter most:

  W1  — the English word comes back as the listener test. English output, the
        developer's own, stays green; every other language is blind again.
  W9  — the strict decode comes back. German still passes (0x99 is defined in
        cp1252); only French-shaped bytes show it.
  B15/B16/B17 — the stamp is taken at the WRONG STEP. The function is fine and
        every stamp_tree test stays green; only the build's own `main`, driven
        end to end, can see a stamp that fingerprints the shim, misses the
        fallback wheel, or counts a file the wheel does not ship.
  C7  — the check compares commits too: stricter-looking, and it refuses the
        ordinary release where two machines built the same source from two
        commits.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every
mutated file must still COMPILE — a mutant that does not parse fails every test
and would be scored as a kill. Both are harness faults, counted OUT.

⚠ EQUIVALENT, AND THEREFORE NOT HERE: `len(parts) < 4` → `< 3` in the parse. A
three-field row that passes the foreign-address test has that address as its
last field, `int("0.0.0.0:0")` raises, and the row is skipped either way.

  .venv/bin/python .mutants/wave109_winport_mutants.py
  .venv/bin/python .mutants/wave109_winport_mutants.py W1 B16
"""
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"
BUILD = "tools/build_compiled.py"
CHECK = "tools/check_release.py"
FILES = (RESEARCH, BUILD, CHECK)
#: Each target runs the suites that can see it; research.py costs ~15 s to import.
SUITES = {
    RESEARCH: "tests/test_port_probe_0916.py tests/test_serve_port_reclaim_0810.py",
    BUILD: "tests/test_release_provenance.py tests/test_compiled_wheel_covers_every_module.py",
    CHECK: "tests/test_release_provenance.py",
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: the netstat parse ─────────────────────────────────────────────
P_FOREIGN = "        if parts[2] not in _NETSTAT_LISTEN_FOREIGN:\n            continue\n"
P_FOREIGN_SET = '_NETSTAT_LISTEN_FOREIGN = ("0.0.0.0:0", "[::]:0")'
P_PORT = '        if parts[1].rpartition(":")[2] != want:\n'
P_PID = ("            pid = int(parts[-1])\n        except ValueError:\n            continue\n"
         "        # 0 is the System Idle Process.")
P_PID0 = "        if pid > 0:\n            pids.add(pid)\n    return pids"
P_LEN = ("        if len(parts) < 4:\n            continue\n"
         "        if parts[2] not in _NETSTAT_LISTEN_FOREIGN:")

# ── anchors: the probe's Windows branch ────────────────────────────────────
N_CMD = '                    ["netstat", "-ano"],\n'
N_DECODE = 'capture_output=True, text=True, errors="replace", timeout=8,'
N_SELF = ('                for pid in _netstat_listening_pids(r.stdout or "", port):\n'
          "                    if pid != me:\n")
N_CALL = '_netstat_listening_pids(r.stdout or "", port)'
N_OK = ("                    if pid != me:\n                        pids.add(pid)\n"
        "                shell_ok = True\n            elif plat in (\"Darwin\", \"Linux\"):")

# ── anchors: stamp_tree ────────────────────────────────────────────────────
S_CRLF = r'path.read_bytes().replace(b"\r\n", b"\n")'
S_MANIFEST = r'manifest = "".join(f"{_lf_sha256(tree / rel)}  {rel}\n" for rel in rels)'
S_RELS = 'rels = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*.py"))'
S_GUARD = '    if "research.py" not in rels:\n        raise SystemExit('
S_WRITE = "    (tree / STAMP_NAME).write_text("
S_NAME = 'STAMP_NAME = "_sr_build.json"'

# ── anchors: the git hints ─────────────────────────────────────────────────
G_TOP = "    if len(out) != 2 or Path(out[0]).resolve() != repo.resolve():"
G_UNKNOWN = "(None if status is None else bool(status.strip()))"
G_DIRTY = "else bool(status.strip()))"
G_COMMIT = "    return out[1].strip(), ("
G_RC = "    return r.stdout if r.returncode == 0 else None"

# ── anchors: where main stamps ─────────────────────────────────────────────
M_CALL = "    stamp = stamp_tree(tree, REPO)\n"
M_BLOCK = ("    stamp = stamp_tree(tree, REPO)\n"
           "    print(f\"[build] {STAMP_NAME}: source_sha256={stamp['source_sha256']} \"\n"
           "          f\"commit={stamp['commit'] or 'unknown'} dirty={stamp['dirty']}\")\n")
M_DROP = "    # 2a. Drop local-only admin scripts"
M_COMPILE = "    # 3a. research.py -> _sr_core.<abi>.pyd"
M_PACK = "    # 4. repack + retag platform-specific"

# ── anchors: check_release ─────────────────────────────────────────────────
C_MANY = "    if len(sources) > 1:"
C_MISSING = ('            problems.append(f"{wheel.name} carries no provenance stamp — built before "\n'
             '                            "stamps existed, or not by tools/build_compiled.py")\n')
C_USABLE = '    if not isinstance(stamp, dict) or not stamp.get("source_sha256"):'
C_EMPTY = "    if not wheels:\n        return False, ["
C_DIR = '        out.extend(sorted(p.glob("*.whl")) if p.is_dir() else [p])'
C_ADD = '        sources.add(stamp["source_sha256"])'
C_EXIT = "    return 0 if ok else 1"
C_EXCEPT = "    except (OSError, KeyError, ValueError, zipfile.BadZipFile):"

MUTANTS = [
    # ── NEW-2: the listener test ───────────────────────────────────────────
    ("W1", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — the English state word is the listener test again. "
     "English output stays green; a German, French or Italian Windows reads a held "
     "port as free",
     [(P_FOREIGN, '        if "LISTENING" not in parts:\n            continue\n')]),

    ("W2", "over", RESEARCH,
     "⛔ no listener test at all: an accepted connection on the port, held by "
     "another process, is reported as a holder and the blunt path kills it",
     [(P_FOREIGN, "")]),

    ("W3", "under", RESEARCH,
     "IPv4-only listener test — a process listening on [::] holds the port "
     "invisibly",
     [(P_FOREIGN_SET, '_NETSTAT_LISTEN_FOREIGN = ("0.0.0.0:0",)')]),

    ("W4", "over", RESEARCH,
     "the port is matched by suffix — 18000's listener is reported as 8000's",
     [(P_PORT, "        if not parts[1].endswith(want):\n")]),

    ("W5", "under", RESEARCH,
     "the pid is read from a fixed column — an Italian 'IN ASCOLTO' pushes it one "
     "along and every listener is dropped",
     [(P_PID, P_PID.replace("parts[-1]", "parts[4]"))]),

    ("W6", "over", RESEARCH,
     "⛔ pid 0 is admitted — the System Idle Process handed to a killer",
     [(P_PID0, "        if pid >= 0:\n            pids.add(pid)\n    return pids")]),

    ("W7", "over", RESEARCH,
     "the short-row guard is gone — a blank line raises IndexError and the whole "
     "probe reads as 'could not look'",
     [(P_LEN, "        if parts[2] not in _NETSTAT_LISTEN_FOREIGN:")]),

    # ── OPS-7 / NEW-2: the probe's Windows branch ──────────────────────────
    ("W8", "under", RESEARCH,
     "`-p TCP` comes back: IPv4 rows only, so the [::] listener never reaches "
     "the parse",
     [(N_CMD, '                    ["netstat", "-ano", "-p", "TCP"],\n')]),

    ("W9", "under", RESEARCH,
     "⛔⛔ the strict decode comes back — French output (0x90 in cp850) raises and "
     "every French machine without psutil reads as 'could not look'",
     [(N_DECODE, "capture_output=True, text=True, timeout=8,")]),

    ("W10", "over", RESEARCH,
     "⛔⛔ the Windows branch reports OUR OWN pid — the caller signals what it is "
     "given, and the backend kills itself at boot",
     [(N_SELF, N_SELF.replace("if pid != me:", "if True:"))]),

    ("W11", "under", RESEARCH,
     "netstat runs and its answer is thrown away — every port reads as free",
     [(N_CALL, '_netstat_listening_pids("", port)')]),

    ("W12", "under", RESEARCH,
     "the parse is always asked about 8000, whatever port the caller named",
     [(N_CALL, '_netstat_listening_pids(r.stdout or "", 8000)')]),

    ("W13", "under", RESEARCH,
     "a netstat that ran and listed nothing reads as 'could not look'",
     [(N_OK, N_OK.replace("                shell_ok = True\n", ""))]),

    # ── OPS-5: what the fingerprint covers ─────────────────────────────────
    ("B1", "over", BUILD,
     "⛔⛔ CRLF is not normalised — every Windows autocrlf wheel reads as different "
     "code from the Mac one, and the check is trained to be ignored",
     [(S_CRLF, "path.read_bytes()")]),

    ("B2", "under", BUILD,
     "every CR is dropped, not just CRLF's — two different programs share a "
     "fingerprint",
     [(S_CRLF, r'path.read_bytes().replace(b"\r", b"")')]),

    ("B3", "under", BUILD,
     "the path leaves the manifest — a rename is not a change",
     [(S_MANIFEST, r'manifest = "".join(f"{_lf_sha256(tree / rel)}\n" for rel in rels)')]),

    ("B4", "over", BUILD,
     "filesystem order enters the fingerprint — NTFS and APFS disagree about the "
     "same tree",
     [(S_RELS, 'rels = [p.relative_to(tree).as_posix() for p in tree.rglob("*.py")]')]),

    ("B5", "over", BUILD,
     "every file counts — a version bump in METADATA reads as different code",
     [(S_RELS, 'rels = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*") '
               'if p.is_file())')]),

    ("B6", "under", BUILD,
     "⛔ a hand-kept list — auth/ and scripts/ ship unfingerprinted, the selfheal "
     "defect in a new place",
     [(S_RELS, 'rels = sorted(["research.py"] + [f"{m}.py" for m in TOP_MODULES])')]),

    ("B7", "under", BUILD,
     "a tree with no pipeline in it is stamped anyway",
     [(S_GUARD, '    if False:\n        raise SystemExit(')]),

    ("B8", "under", BUILD,
     "⛔ a copy inside another repository borrows that repository's commit",
     [(G_TOP, "    if len(out) != 2:")]),

    ("B9", "under", BUILD,
     "a status git refused reads as a confident 'clean'",
     [(G_UNKNOWN, 'bool((status or "").strip())')]),

    ("B10", "under", BUILD,
     "dirty is inverted",
     [(G_DIRTY, "else not status.strip())")]),

    ("B11", "under", BUILD,
     "the commit is the top-level PATH, not HEAD",
     [(G_COMMIT, "    return out[0].strip(), (")]),

    ("B12", "under", BUILD,
     "git's exit code is ignored — a repository with no commit is stamped "
     "commit='HEAD'",
     [(G_RC, "    return r.stdout")]),

    ("B13", "under", BUILD,
     "the stamp is computed and never written where the wheel packs it",
     [(S_WRITE, "    (tree / 'stamp.unused').write_text(")]),

    ("B14", "under", BUILD,
     "⛔⛔ main never stamps — the function is tested and nothing calls it",
     [(M_CALL, '    stamp = {"source_sha256": "", "commit": None, "dirty": None}\n')]),

    ("B15", "over", BUILD,
     "⛔ stamped BEFORE the drop — the fingerprint counts a script the wheel does "
     "not ship, so a clean clone and a working tree disagree",
     [(M_CALL, ""), (M_DROP, M_CALL + M_DROP)]),

    ("B16", "under", BUILD,
     "⛔⛔ stamped AFTER the compile — research.py is the shim by then and the "
     "siblings are gone, and the source fallback carries no stamp at all",
     [(M_BLOCK, ""), (M_PACK, "    stamp_tree(tree, REPO)\n" + M_PACK)]),

    ("B17", "under", BUILD,
     "⛔ stamped after the source fallback is packed — the fallback wheel joins "
     "the release unstamped",
     [(M_BLOCK, ""), (M_COMPILE, "    stamp_tree(tree, REPO)\n" + M_COMPILE)]),

    ("B18", "under", BUILD,
     "git is asked about the temporary tree — every build is stamped commit=None",
     [(M_CALL, "    stamp = stamp_tree(tree, tree)\n")]),

    ("B19", "under", BUILD,
     "the build writes a name the check does not read",
     [(S_NAME, 'STAMP_NAME = "sr_build.json"')]),

    # ── OPS-5: the release check ───────────────────────────────────────────
    ("C1", "under", CHECK,
     "⛔⛔ one wheel of a different source is let through",
     [(C_MANY, "    if len(sources) > 2:")]),

    ("C2", "under", CHECK,
     "⛔ a wheel with no stamp joins the release as long as the others agree",
     [(C_MISSING, "")]),

    ("C3", "under", CHECK,
     "a stamp with no fingerprint counts as a stamp",
     [(C_USABLE, "    if not isinstance(stamp, dict):")]),

    ("C4", "under", CHECK,
     "a stamp that is not an object is read as one",
     [(C_USABLE, '    if not stamp.get("source_sha256"):')]),

    ("C5", "under", CHECK,
     "⛔ no wheels at all is a pass — an empty glob checked nothing and said OK",
     [(C_EMPTY, "    if False:\n        return False, [")]),

    ("C6", "under", CHECK,
     "a staging directory is read as a wheel instead of for its wheels",
     [(C_DIR, "        out.append(p)")]),

    ("C7", "over", CHECK,
     "⛔ commits are compared too — the same source built from two commits is "
     "refused, and the ordinary release cannot publish",
     [(C_ADD, '        sources.add((stamp["source_sha256"], stamp.get("commit")))')]),

    ("C8", "under", CHECK,
     "⛔⛔ the verdict is printed and the exit code always says OK",
     [(C_EXIT, "    return 0")]),

    ("C9", "under", CHECK,
     "a wheel that is not a zip, or a stamp that is not JSON, crashes the check "
     "instead of refusing it",
     [(C_EXCEPT, "    except (OSError, KeyError):")]),

    ("C10", "under", CHECK,
     "the check reads a name the build does not write",
     [(S_NAME, 'STAMP_NAME = "sr_build.json"')]),
]


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, env=ENV, shell=True,
                          capture_output=True, text=True)


def green(suites):
    # ⭐ THE INTERPRETER RUNNING THIS FILE, so a worktree with no `.venv` of its
    # own still measures its own tree (pytest puts the cwd first on sys.path).
    r = _run(f"{shlex.quote(sys.executable)} -m pytest {suites} -q -p no:cacheprovider")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it. An ERROR (a fixture or
    # collection fault) is red too, not only a failure.
    return (re.search(r"\b\d+ (failed|errors?)\b", out) is None
            and re.search(r"\b\d+ passed\b", out) is not None)


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
    for fname in FILES:
        if not green(SUITES[fname]):
            print(f"⛔ BASELINE RED ({SUITES[fname]}) — fix the suite before mutating anything.")
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
            if green(SUITES[fname]):
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
