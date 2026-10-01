"""Mutation harness — the Windows review of wave 13 (2026-09-30).

⛔⛔ WHAT THIS CODE DECIDES.
  P* — research.py: where Windows' list of research.py processes comes from
       (psutil — the name first — then PowerShell's CIM, then WMIC; WMIC is gone
       from current Windows 11), a process's age, this worker's own venv
       launcher (the supervisor one step above it; never stopped by an update),
       and Reset Backend asking about ITS supervisor. Move to queue, --retire,
       --resurrect and the update all read these.
  C* — research.py: the Copy backup's brief is read back with LF line ends.
  H* — research.py: the clipboard hooks run in the page's own script world
       (patchright 1.62+ runs evaluate isolated, where a hook sees nothing).

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE, and every mutated
Python file must still COMPILE. Both are harness faults, counted OUT.
⛔ BYTES BACK, NOT TEXT — a text restore would flip a CRLF checkout's line endings.
⛔⛔ AN IN-FLIGHT MARKER, because Windows kills without running `finally:` or a
SIGTERM handler. Run this in a throwaway worktree, never in the checkout the
backend runs from. On Windows the suite also runs the real process-table tests
(a pass there takes about a minute — run a few mutants at a time, or on Linux).

  python .mutants/windows_review_w13_mutants.py
  python .mutants/windows_review_w13_mutants.py P6 C1 H1
"""
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESEARCH = "research.py"

SUITES = {
    RESEARCH: (ROOT, "tests/test_windows_review_w13.py"),
}
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

MUTANTS = [
    ('P1', RESEARCH, '⛔⛔ psutil is not asked — PowerShell (or WMIC) every time',
     [('    rows = _windows_python_procs_psutil()\n    if rows is None:\n        rows = _windows_python_procs_cim()\n',
       '    rows = None\n    if rows is None:\n        rows = _windows_python_procs_cim()\n')]),
    ('P2', RESEARCH, '⛔⛔ no CIM — a Windows without psutil and WMIC lists nothing again',
     [('    if rows is None:\n        rows = _windows_python_procs_cim()\n',
       '    if rows is None:\n        rows = None\n')]),
    ('P3', RESEARCH, "⛔ one python process: ConvertTo-Json's object is not read",
     [('    if isinstance(data, dict):               # one process: ConvertTo-Json gives an object\n        data = [data]\n',
       '    if isinstance(data, dict):               # one process: ConvertTo-Json gives an object\n        pass\n')]),
    ('P4', RESEARCH, '⛔ psutil lists every program, not only python — a Chrome naming research.py is listed',
     [('                if str(info.get("name") or "").lower() not in _WIN_PYTHON_NAMES:\n                    continue\n',
       '                if False:\n                    continue\n')]),
    ('P5', RESEARCH, '⛔ the command line loses its quotes (a path with a space splits)',
     [('rows.append((int(info["pid"]), subprocess.list2cmdline([str(a) for a in args])))',
       'rows.append((int(info["pid"]), " ".join([str(a) for a in args])))')]),
    ('P6', RESEARCH, '⛔⛔ the venv launcher is not stepped over — pipx installs never supervised',
     [('    above_launcher = _venv_launcher_parent(ppid)\n',
       '    above_launcher = None\n')]),
    ('P7', RESEARCH, '⛔ the launcher step runs on macOS/Linux too, where a same-arguments parent is a fork',
     [('    if _supervisor_platform() != "Windows":\n        return False\n    try:\n        import psutil as _ps\n        me, parent',
       '    if False:\n        return False\n    try:\n        import psutil as _ps\n        me, parent')]),
    ('P8', RESEARCH, "⛔⛔ any python parent is taken for a launcher — another worker's supervisor",
     [('        if not theirs or theirs[1:] != mine[1:]:\n',
       '        if not theirs:\n')]),
    ('P9', RESEARCH, "⛔ a process's age from WMIC only — None on current Windows 11",
     [('        return max(0.0, time.time() - _ps.Process(int(pid)).create_time())\n',
       '        raise RuntimeError("no psutil age")\n')]),
    ('P10', RESEARCH, "⛔ every process's command line is read before its name — ~5 s a scan, elevated",
     [('                info = proc.info\n                if str(info.get("name") or "").lower() not in _WIN_PYTHON_NAMES:\n',
       '                info = proc.info\n                proc.cmdline()\n                if str(info.get("name") or "").lower() not in _WIN_PYTHON_NAMES:\n')]),
    ('P11', RESEARCH, '⛔ another program with the same arguments is taken for the launcher',
     [('        if str(parent.name()).lower() != str(me.name()).lower():\n            return False\n',
       '        if False:\n            return False\n')]),
    ('P12', RESEARCH, '⛔ a python outside any venv is taken for a launcher',
     [('        return (Path(parent.exe()).parent.parent / "pyvenv.cfg").is_file()\n',
       '        return True\n')]),
    ('P13', RESEARCH, "⛔⛔ an update stops this worker's own launcher — and with it this worker, mid-list",
     [('        if _is_my_venv_launcher(os.getppid()):\n            spare.add(os.getppid())\n',
       '        if False:\n            spare.add(os.getppid())\n')]),
    ('P14', RESEARCH, '⛔⛔ Reset Backend asks whether ANY daemon-loop runs — a foreground --serve beside the fleet exits for good',
     [('                    _supervisor_alive = _supervisor_is_my_parent()\n',
       '                    _supervisor_alive = any(r == "daemon-loop" and p != os.getpid()\n                                            for p, _c, r in _enumerate_research_py_procs())\n')]),
    ('P15', RESEARCH, "⛔ a profile's Chrome is found by reading every process's command line — 5 s a scan, elevated",
     [('            if not (proc.info["name"] and "chrom" in proc.info["name"].lower()):\n                continue\n            args = proc.info["cmdline"] if "cmdline" in proc.info else proc.cmdline()\n',
       '            proc.cmdline() if "cmdline" not in proc.info else None\n            if not (proc.info["name"] and "chrom" in proc.info["name"].lower()):\n                continue\n            args = proc.info["cmdline"] if "cmdline" in proc.info else proc.cmdline()\n')]),
    ('C1', RESEARCH, "⛔⛔ the Copy backup's brief keeps CRLF — brief.md written CR CR LF, tables broken",
     [('            return got.replace("\\r\\n", "\\n").replace("\\r", "\\n")\n',
       '            return got\n')]),
    ('C2', RESEARCH, '⛔ a lone CR is kept',
     [('            return got.replace("\\r\\n", "\\n").replace("\\r", "\\n")\n',
       '            return got.replace("\\r\\n", "\\n")\n')]),
    ('H1', RESEARCH, '⛔⛔ the one-shot Copy hijack runs isolated — on patchright 1.62+ it catches nothing',
     [('        result = await _page_world_evaluate(page, r"""(opts) => new Promise(async (resolve) => {\n',
       '        result = await page.evaluate(r"""(opts) => new Promise(async (resolve) => {\n')]),
    ('H2', RESEARCH, "⛔⛔ the Tier-3 hook is installed isolated — the page's own Copy is never seen",
     [('                ok = await _page_world_evaluate(tgt, install_script)\n',
       '                ok = await tgt.evaluate(install_script)\n')]),
    ('H3', RESEARCH, "⛔ the page's world is not asked for",
     [('        return await target.evaluate(js, *args, isolated_context=False)\n',
       '        return await target.evaluate(js, *args, isolated_context=True)\n')]),
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
