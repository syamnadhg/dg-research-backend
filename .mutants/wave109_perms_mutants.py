"""Wave 10.9 — are the research computer's keys and records its owner's alone?

⛔⛔ WHAT THE WAVE CLOSED (#538, security N4, the queues/ root). Every API-key
save rewrote `.dg-supervisor.env` through `tmp.write_text(); tmp.replace(target)`
— and the rename hands the target the TEMP file's inode at the umask's 0644, so
the seed's 0600 lasted exactly until the first key was pasted. The owner's Mac
measured -rw-r--r-- on the keys file, drwxr-xr-x on ~/.super-research, logs/,
runs/, sessions/, outgoing/ and queues/, and -rw-r--r-- on the support zips and
keystore-audit.log, under a home every macOS account can traverse (0750,
group staff). The fix is two halves: one writer that is 0600 from its first
byte, and one boot hook in main() that narrows what is already on disk.

Every mutant below is a way the fix could be put back to decoration while still
looking installed. The ones that matter most are the quiet ones:

  K5  — the writer "preserves the file's existing permissions". The most
        reasonable-looking edit in the list, and on every machine that already
        has the key file it restores the 0644 exactly.
  K6  — the shared atomic writer's temp is opened readable. The keys file's
        privacy rides on mkstemp's O_EXCL 0600 inside `_atomic_write_text`, a
        function whose name says nothing about privacy.
  B2  — only the long-running processes harden. Looks like a sensible "why do
        this on --help" saving, and the call is still there to grep.
  L4  — the walk covers run logs only. The support ZIPS are the one thing a
        person attaches to an email; leaving outgoing/ open is the whole N4.
  P3  — the narrower forces 0600 on everything, so every directory it touches
        loses its x bit and the OWNER is locked out of their own logs. The
        over-correction that "readable only by its owner" invites.
  S1/S2 — the hook follows a link out of the tree and re-permissions somebody's
        file elsewhere on the disk.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. So is a
mutant whose text does not PARSE: an unparseable research.py reds the suite on
an import error and would bank a kill nothing earned, so each mutated file is
ast.parse()d before it is written.

⭐ EQUIVALENT, AND THEREFORE NOT HERE (proved, not assumed):
  * `mode=0o700` on the queues mkdir — the very next line narrows the directory
    whether it was just made or already there, so no observable state differs.
    It stays in the source to make the directory private from birth.
  * `if mode & 0o077:` in `_owner_only` — without it the chmod writes the mode
    the path already has.
  * a chmod of the key file after the rename — mkstemp already made it 0600, so
    the harness would record a survivor that is a no-op. The source has none.

  <venv python> -u .mutants/wave109_perms_mutants.py
  <venv python> -u .mutants/wave109_perms_mutants.py K1 B2
"""
import ast
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_owner_only_perms_109.py "
          "tests/test_pair_prompt.py "
          # `_atomic_write_text` carries a new load-bearing comment and K6 edits
          # it; this is the suite that exercises its other caller.
          "tests/test_cloud_log_pull_0901.py")
RESEARCH = "research.py"
FILES = (RESEARCH,)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
# ⭐ THE INTERPRETER RUNNING THIS FILE, not `.venv/bin/python`: a builder's
# worktree has no .venv of its own, and a harness that cannot start its suite
# reports every mutant killed.
PY = shlex.quote(sys.executable)

# ── anchors: research.py ────────────────────────────────────────────────────
SAVE_WRITE = ("        _write_owner_only_text(target, out)\n"
              "        return True\n"
              "    except Exception as e:\n"
              "        log(f\"[save-api-key-local] write")
CLEAR_WRITE = ("        _write_owner_only_text(target, out)\n"
               "        return True\n"
               "    except Exception as e:\n"
               "        log(f\"[clear-api-key-local] clear")
SEED_WRITE = "        _write_owner_only_text(target, example.read_text(encoding=\"utf-8-sig\"))"
HELPER_BODY = "    _atomic_write_text(Path(path), text, create_parents=False)"
MKSTEMP = ("    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), "
           "prefix=path.name + \".\", suffix=\".tmp\")")
MAIN_CALL = ("    _harden_owner_only_paths()\n"
             "\n"
             "    # Load .dg-supervisor.env BEFORE")
WIN_GUARD = ("    if sys.platform == \"win32\":\n"
             "        return  # mode bits mean next to nothing on NTFS")
QUEUES_FN = ("    the worker locks and `setup_firestore_run` spell out inline.\"\"\"\n"
             "    return Path(__file__).parent / \"queues\"")

MUTANTS = [
    # ── K: the writers ───────────────────────────────────────────────────────
    ("K1", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — the key save goes back to write-then-rename, and "
     "the rename re-creates the keys file at 0644 on every paste",
     [(SAVE_WRITE,
       "        tmp = target.with_suffix(target.suffix + \".tmp\")\n"
       "        tmp.write_text(out, encoding=\"utf-8\")\n"
       "        tmp.replace(target)\n"
       "        return True\n"
       "    except Exception as e:\n"
       "        log(f\"[save-api-key-local] write")]),

    ("K2", "under", RESEARCH,
     "⛔⛔ the clear goes back to write-then-rename — and the file it rewrites "
     "still holds every OTHER key",
     [(CLEAR_WRITE,
       "        tmp = target.with_suffix(target.suffix + \".tmp\")\n"
       "        tmp.write_text(out, encoding=\"utf-8\")\n"
       "        tmp.replace(target)\n"
       "        return True\n"
       "    except Exception as e:\n"
       "        log(f\"[clear-api-key-local] clear")]),

    ("K3", "under", RESEARCH,
     "the seed goes back to a plain write with no chmod after it — a fresh "
     "install's keys file is born 0644 and the first save keeps that",
     [(SEED_WRITE,
       "        target.write_text(example.read_text(encoding=\"utf-8-sig\"), encoding=\"utf-8\")")]),

    ("K4", "under", RESEARCH,
     "⛔ the owner-only writer is hollowed to a plain write_text — still called "
     "from all three sites, still greppable, and neither atomic nor private",
     [(HELPER_BODY, "    Path(path).write_text(text, encoding=\"utf-8\")")]),

    ("K5", "under", RESEARCH,
     "⛔⛔ THE WRITER 'PRESERVES THE FILE'S EXISTING PERMISSIONS' — the most "
     "reasonable-looking edit here, and on every machine that already has the "
     "keys file it restores the 0644 exactly",
     [(HELPER_BODY,
       "    _old = os.stat(path).st_mode if os.path.exists(path) else None\n"
       "    _atomic_write_text(Path(path), text, create_parents=False)\n"
       "    if _old is not None:\n"
       "        os.chmod(path, _old)")]),

    ("K6", "under", RESEARCH,
     "⛔⛔ the shared atomic writer's temp is opened readable — the keys file's "
     "privacy rides on mkstemp's 0600 inside a function whose name says nothing "
     "about privacy",
     [(MKSTEMP, MKSTEMP + "\n    os.chmod(tmp_path, 0o644)")]),

    # ── B: the boot hook's consumer ─────────────────────────────────────────
    ("B1", "under", RESEARCH,
     "⛔⛔ the boot call is deleted — the hook is defined, tested in isolation, "
     "and never runs, so nothing already on disk is ever narrowed",
     [(MAIN_CALL, "\n    # Load .dg-supervisor.env BEFORE")]),

    ("B2", "under", RESEARCH,
     "⛔ only the long-running processes harden — a plausible 'why do this on "
     "--help' saving that leaves every interactive command's disk open",
     [(MAIN_CALL,
       "    if args.serve or args.daemon_loop:\n"
       "        _harden_owner_only_paths()\n"
       "\n"
       "    # Load .dg-supervisor.env BEFORE")]),

    ("B3", "over", RESEARCH,
     "a custom --env-file is chmodded too — a file the user pointed us at, "
     "possibly shared on purpose, is not ours to re-permission",
     [(MAIN_CALL,
       "    _harden_owner_only_paths()\n"
       "    if args.env_file:\n"
       "        _owner_only(args.env_file)\n"
       "\n"
       "    # Load .dg-supervisor.env BEFORE")]),

    # ── H: what the hook covers ─────────────────────────────────────────────
    ("H1", "under", RESEARCH,
     "⛔⛔ the keys file drops out of the hook — the writers fix the NEXT save, "
     "and a machine that never saves again keeps its 0644 keys for ever",
     [("        for p in (env_file,\n", "        for p in (\n")]),

    ("H2", "under", RESEARCH,
     "a pre-#538 save that died mid-rename left the key in the fixed-name .tmp "
     "at 0644, and nothing narrows it",
     [("                  env_file.with_name(env_file.name + \".tmp\"),\n", "")]),

    ("H3", "under", RESEARCH,
     "the state dir stays 0755 — run_analytics.json, telemetry/ and every file "
     "written after boot stay reachable",
     [("                  _STATE_DIR,\n", "")]),

    ("H4", "under", RESEARCH,
     "the keystore audit log stays -rw-r--r--",
     [("                  _STATE_DIR / \"keystore-audit.log\",\n", "")]),

    ("H5", "under", RESEARCH,
     "the self-heal audit log stays -rw-r--r--",
     [("                  _STATE_DIR / \"keystore-audit.log\",\n"
       "                  _STATE_DIR / \"selfheal-audit.log\"):",
       "                  _STATE_DIR / \"keystore-audit.log\"):")]),

    ("Q1", "under", RESEARCH,
     "⛔ queues/ is only narrowed, never created — a worker makes it AFTER boot, "
     "so a fresh install leaves its run folders open for the whole life of "
     "its first serve",
     [("            queues.mkdir(mode=0o700, exist_ok=True)", "            pass")]),

    ("Q2", "under", RESEARCH,
     "⛔⛔ an existing queues/ is never narrowed — the owner's own 0755 folder of "
     "topic-named runs stays listable",
     [("        _owner_only(queues)\n", "")]),

    ("Q3", "under", RESEARCH,
     "the queues root resolves somewhere the workers do not write, and the hook "
     "narrows an empty directory beside the real one",
     [(QUEUES_FN,
       "    the worker locks and `setup_firestore_run` spell out inline.\"\"\"\n"
       "    return Path(__file__).parent / \"queue\"")]),

    ("L1", "under", RESEARCH,
     "the walk narrows files but not directories — runs/, sessions/ and "
     "outgoing/ stay listable",
     [("            _owner_only(root)\n", "")]),

    ("L2", "under", RESEARCH,
     "the walk narrows directories but not files — every run log and zip keeps "
     "its 0644",
     [("                _owner_only(os.path.join(root, name))", "                pass")]),

    ("L3", "under", RESEARCH,
     "the walk stops at the top of logs/ — backend.log is narrowed, runs/, "
     "sessions/ and outgoing/ are not",
     [("        for root, _dirs, files in os.walk(_logs_root()):",
       "        for root, _dirs, files in list(os.walk(_logs_root()))[:1]:")]),

    ("L4", "under", RESEARCH,
     "⛔⛔ THE WALK COVERS RUN LOGS ONLY — the support zips are the one thing a "
     "person attaches to an email, and outgoing/ is the whole of N4",
     [("        for root, _dirs, files in os.walk(_logs_root()):",
       "        for root, _dirs, files in os.walk(_runs_log_root()):")]),

    # ── P / S: how one path is narrowed ─────────────────────────────────────
    ("P1", "under", RESEARCH,
     "other accounts keep READ — only the group bits come off",
     [("            os.chmod(path, mode & ~0o077)", "            os.chmod(path, mode & ~0o070)")]),

    ("P2", "under", RESEARCH,
     "the group keeps READ — and on macOS the group is staff, every account",
     [("            os.chmod(path, mode & ~0o077)", "            os.chmod(path, mode & ~0o007)")]),

    ("P3", "over", RESEARCH,
     "⛔⛔ EVERYTHING FORCED TO 0600 — every directory loses its x bit and the "
     "OWNER is locked out of their own logs and runs",
     [("            os.chmod(path, mode & ~0o077)", "            os.chmod(path, 0o600)")]),

    ("S1", "over", RESEARCH,
     "⛔ a symlink is followed and whatever it points at is re-permissioned, "
     "anywhere on the disk",
     [("        if _stat.S_ISLNK(st.st_mode):\n            return\n", "")]),

    ("S2", "over", RESEARCH,
     "the walk descends through a linked directory and narrows files outside "
     "the tree",
     [("        for root, _dirs, files in os.walk(_logs_root()):",
       "        for root, _dirs, files in os.walk(_logs_root(), followlinks=True):")]),

    # ── W / F: the platform gate and failure containment ────────────────────
    ("W1", "under", RESEARCH,
     "⛔ the Windows gate is inverted — POSIX, the only place the mode bits "
     "mean anything, is the platform that gets skipped",
     [(WIN_GUARD,
       "    if sys.platform != \"win32\":\n"
       "        return  # mode bits mean next to nothing on NTFS")]),

    ("W2", "over", RESEARCH,
     "the Windows gate is removed, so NTFS gets chmods that mean nothing there",
     [(WIN_GUARD,
       "    if False:\n"
       "        return  # mode bits mean next to nothing on NTFS")]),

    ("F1", "under", RESEARCH,
     "⛔ one path that refuses its chmod stops the whole hook — a single "
     "root-owned file in logs/ leaves the zips and the queues root open",
     [("            os.chmod(path, mode & ~0o077)\n"
       "    except OSError:\n"
       "        pass",
       "            os.chmod(path, mode & ~0o077)\n"
       "    except FileNotFoundError:\n"
       "        pass")]),

    ("F2", "under", RESEARCH,
     "⛔⛔ the hook can raise into main() — every command on the machine, "
     "--pair and --serve included, dies on a filesystem hiccup in logs/",
     [("                _owner_only(os.path.join(root, name))\n"
       "    except Exception:\n"
       "        pass",
       "                _owner_only(os.path.join(root, name))\n"
       "    except OSError:\n"
       "        pass")]),
]


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, env=ENV, shell=True,
                          capture_output=True, text=True)


def _summary(out):
    lines = [ln for ln in out.splitlines()
             if " passed" in ln or " failed" in ln or " error" in ln]
    return lines[-1].strip() if lines else "(no summary line)"


def green():
    r = _run(f"{PY} -m pytest {SUITES} -q -p no:cacheprovider")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it. An ERROR is not green
    # either: a fixture that cannot build measured nothing.
    s = _summary(out)
    return "passed" in s and "failed" not in s and "error" not in s, out


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY, and the sweep is why. The
# static anchor sweep loads every harness in this directory with
# `spec.loader.exec_module`, which EXECUTES it — so an unguarded runner turns a
# seconds-long static check into a full mutation run.
if __name__ == "__main__":
    ORIGINALS = {f: (ROOT / f).read_text(encoding="utf-8") for f in FILES}


    def restore():
        for f, t in ORIGINALS.items():
            (ROOT / f).write_text(t, encoding="utf-8")


    only = set(sys.argv[1:])
    print("baseline… ", end="", flush=True)
    ok, out = green()
    if not ok:
        print("⛔ BASELINE RED — fix the suite before mutating anything.")
        print(out[-3000:])
        sys.exit(2)
    # ⛔ A SKIP IS THE ABSENCE OF A MEASUREMENT. A baseline that skipped would
    # score its mutants over tests that never ran.
    if " skipped" in _summary(out):
        print(f"⛔ BASELINE SKIPPED TESTS — {_summary(out)}")
        sys.exit(2)
    print(f"green ({_summary(out)})\n")

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
            try:
                ast.parse(mutated)
            except SyntaxError as e:
                raise AssertionError(f"mutant does not parse: {e}")
            path.write_text(mutated, encoding="utf-8")
            alive, _out = green()
            if alive:
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
