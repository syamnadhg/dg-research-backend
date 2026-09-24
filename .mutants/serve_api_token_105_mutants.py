"""Wave 10.5 — can the guards actually see the local API being left open?

⛔⛔ WHAT THE WAVE CLOSED. `--serve` ran an HTTP API that authenticated nobody.
Fourteen routes listed every run on the machine across every account, served
the briefs, the reports and the podcasts, stopped and deleted somebody's
research, and started a new one **billing the Firebase account named in the
request body**. Loopback binding (09-05) narrowed the audience and the wave that
did it wrote a test saying, in its own words, that it was not authentication.

Every mutant below is a way the gate could be put back to decoration while
still looking installed. The ones that matter most are the quiet ones:

  S1  — the gate fails OPEN when it cannot read the token. "We could not
        check, so allow" is how a gate becomes a comment.
  S4  — the exemption becomes a PREFIX, so `/api/health-runs` walks through and
        the whole thing is one route name away from off.
  S6  — the exclusive create becomes an ordinary one, so N booting workers each
        mint a token and the last one invalidates everybody else's.
  S10 — a `?token=` convenience is added, putting the secret in uvicorn's
        access log, in shell history and in every proxy in between. THIS ONE
        EXISTS BECAUSE ITS GUARD CANNOT FAIL WITHOUT IT: a test that a feature
        is absent measures nothing until something adds the feature.
        (⛔ This bullet said S11 until 2026-09-20 — cross-verify caught it. A
        roster that misnames its own mutants sends the next reviewer to spot-
        check the wrong one and record the right one as re-verified.)
  R1  — the two middlewares are swapped. Starlette makes the LAST-added the
        OUTERMOST, so this puts the gate outside CORS, where it answers the
        browser's preflight — which carries no header to authenticate with —
        and every cross-origin call 401s before the origin policy runs.
  R3  — the caller's uid mismatch stops being refused. `if False:` keeps every
        symbol a looser assertion would look for.
  C1  — conftest stops redirecting the token directory, and the suite mints a
        live credential into the developer's own `~/.super-research/`.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT.

⭐ NO `-k` FILTER HERE, DELIBERATELY. The two suites run are exactly the two
files this step owns, so "this step's own guards" and "the whole selection" are
the same set and a filter could only subtract. `_filter_misses` is kept for the
next harness that needs it.

  .venv/bin/python .mutants/serve_api_token_105_mutants.py
  .venv/bin/python .mutants/serve_api_token_105_mutants.py S4 R1
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_serve_api_token_105.py "
          "tests/test_serve_api_exposure_77f.py")

OWNED_FILES = ("tests/test_serve_api_token_105.py",
               "tests/test_serve_api_exposure_77f.py")

TOKEN = "auth/serve_token.py"
RESEARCH = "research.py"
CONFTEST = "tests/conftest.py"
FILES = (TOKEN, RESEARCH, CONFTEST)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors: auth/serve_token.py ─────────────────────────────────────────────
#: The fail-closed line, comment and all.
FAIL_CLOSED = "        return False  # ⛔ FAIL CLOSED — no secret means no access, not free access."
#: The constant-time comparison.
COMPARE = '    return hmac.compare_digest(presented.encode("utf-8"), stored.encode("utf-8"))'
#: The re-harden condition.
HARDEN = "    if mode & 0o077:"
#: The exemption test — exact membership, trailing slash normalised.
EXEMPT_TEST = '    return (path.rstrip("/") or "/") in EXEMPT_PATHS'
#: The exclusive create that settles the multi-worker mint race.
EXCL = "os.O_CREAT | os.O_EXCL | os.O_WRONLY"
#: The secret's length.
SIZE = "_TOKEN_BYTES: Final = 32"
#: The protocols the gate covers.
PROTOCOLS = '        if kind not in ("http", "websocket"):'
#: The tail of the header read — where a query-string fallback would go.
HEADER_TAIL = ("            except UnicodeDecodeError:\n"
               "                return None\n"
               "    return None\n")
#: The 401 body's one reference to the file.
BODY_FILE = ('                   f"{TOKEN_FILENAME}, beside the keystore — the --serve "\n'
             '                   "banner prints the full path"),')
#: The exemption set itself.
EXEMPT_SET = 'EXEMPT_PATHS: Final[frozenset[str]] = frozenset({"/api/health"})'

# ── anchors: research.py ─────────────────────────────────────────────────────
#: The gate's installation.
INSTALL = "    app.add_middleware(ServeTokenMiddleware)\n"
#: The end of the CORS call it must sit ABOVE.
CORS_END = '        allow_headers=["*"],\n    )\n'
#: The identity the run is billed to.
UID = '        uid = load_paired_uid() or ""'
#: The refusal of a uid the caller named.
MISMATCH = "        if _claimed and _claimed != uid:"
#: The JSON coercion that keeps a dict from turning a 403 into a 500.
COERCE = '        _claimed = str(request_data.get("uid") or "").strip()'
#: The boot-time mint.
MINT_AT_BOOT = "    try:\n        ensure_token()\n"
#: The last row of the --help reference table.
REFERENCE_TAIL = ('    ("GET  /api/health",                    '
                  '"Liveness + heartbeat counters (no token needed)"),')
#: The banner row — the PATH, never the value.
BANNER_ROW = '        _token_row = [("API token", _c(_DIM, str(_srv_token_path())))]'

# ── anchors: tests/conftest.py ───────────────────────────────────────────────
#: The suite-wide redirect that keeps a test off the developer's real home.
ISOLATION = '    monkeypatch.setattr(serve_token, "_KEYSTORE_DIR", _serve_token_dir)'
#: The decode guard that turns an unreadable token file into a refusal.
READ_GUARD = "    except (OSError, UnicodeDecodeError):"
#: The clear-and-remint that stops a zero-byte file bricking the machine.
EMPTY_CLEAR = ("    if _clear_empty:\n"
               "        try:\n"
               "            if path.exists() and not path.read_bytes().strip():")
#: The enqueued payload — the identity that actually reaches the worker.
ENQUEUE = '"run_id": run_id, "uid": uid, "brief_text": brief_text})'
#: The destructive route's reference row.
DELETE_ROW = ('    ("DELETE /api/runs/{id}",               '
              '"Delete a run\'s queue dir (destructive)"),\n')

MUTANTS = [
    ("S1", "under", TOKEN,
     "⛔⛔⛔ THE GATE FAILS OPEN. With no readable token file every request is "
     "waved through instead of refused — 'we could not check, so allow'. A "
     "machine whose token was deleted, or whose home is on an unmounted "
     "volume, is back to exactly the API this wave existed to close",
     [(FAIL_CLOSED, FAIL_CLOSED.replace("return False", "return True"))]),

    ("S2", "under", TOKEN,
     "⛔ the secret is compared with `==`, which returns on the first wrong "
     "byte. A local caller can time a local request very precisely, so the "
     "token becomes guessable one character at a time",
     [(COMPARE, "    return presented == stored")]),

    ("S3", "under", TOKEN,
     "⛔ a widened mode is left widened. A backup tool, an rsync or a careless "
     "chmod makes the token group/world readable and every later boot accepts "
     "what it finds",
     [(HARDEN, "    if False:")]),

    ("S4", "under", TOKEN,
     "⛔⛔ THE EXEMPTION BECOMES A PREFIX. `/api/health-runs`, "
     "`/api/healthcheck` — anything that starts with the one exempt path walks "
     "through, and the gate is one route name away from being off entirely",
     [(EXEMPT_TEST, '    return path.startswith("/api/health")')]),

    ("S5", "over", TOKEN,
     "the trailing-slash normalisation goes, so `/api/health/` answers 401. "
     "FastAPI's slash redirect happens INSIDE the router — after this gate — "
     "so the probe's own redirect would be refused and the watchdog would "
     "force-respawn a healthy worker",
     [(EXEMPT_TEST, "    return path in EXEMPT_PATHS")]),

    ("S6", "under", TOKEN,
     "⛔⛔ the exclusive create becomes an ordinary one. `--serve` boots N "
     "worker PROCESSES together; each mints its own token and the last write "
     "silently invalidates the one every other worker already handed out. The "
     "machine 401s itself with nothing actually wrong",
     [(EXCL, "os.O_CREAT | os.O_WRONLY")]),

    ("S7", "under", TOKEN,
     "⛔ the secret shrinks to four bytes. Short enough that a local process "
     "can simply try them all against a loopback port that answers instantly",
     [(SIZE, "_TOKEN_BYTES: Final = 4")]),

    ("S8", "over", TOKEN,
     "⛔ the gate stops letting `lifespan` past, so startup and shutdown events "
     "are answered with an HTTP 401 frame on a channel that speaks neither. "
     "Every worker breaks at boot — the loud failure, but a real one",
     [(PROTOCOLS, "        if False:")]),

    ("S9", "under", TOKEN,
     "⛔ websockets stop being gated. The `/ws/{run_id}` route was deleted in "
     "April; the day one comes back it arrives OPEN, and nobody adding a route "
     "would think to check a middleware they did not write",
     [(PROTOCOLS, '        if kind != "http":')]),

    ("S10", "under", TOKEN,
     "⛔⛔ A `?token=` CONVENIENCE IS ADDED. The secret then lands in uvicorn's "
     "access log, in shell history, in the browser's own history and in every "
     "proxy in between — a credential that leaks by being used. ⭐ This mutant "
     "is why the query-string test is a measurement: without something that "
     "ADDS the feature, a test that a feature is absent cannot fail",
     [(HEADER_TAIL,
       "            except UnicodeDecodeError:\n"
       "                return None\n"
       "    from urllib.parse import parse_qs as _pq\n"
       '    _q = _pq((scope.get("query_string") or b"").decode("utf-8", "ignore"))\n'
       '    for _k in ("token", HEADER, "access_token"):\n'
       "        if _q.get(_k):\n"
       "            return _q[_k][0]\n"
       "    return None\n")]),

    ("S11", "under", TOKEN,
     "⛔⛔ the 401 body hands out the very secret it is refusing. Every rejected "
     "caller — including the one that had no business asking — is told the "
     "answer, and it goes into whatever log caught the response",
     # ⛔ THE LEAK GOES IN THE **f-STRING** LINE. The first version of this
     # mutant appended `{read_token()}` to the PLAIN second line, where it is
     # literal text — so no token ever appeared, the guard passed honestly, and
     # the mutant survived while measuring nothing.
     [(BODY_FILE, BODY_FILE.replace(
         'f"{TOKEN_FILENAME}, beside the keystore — the --serve "',
         'f"{TOKEN_FILENAME} holds {read_token()}; the --serve "'))]),

    ("S12", "under", TOKEN,
     "⛔ the exemption set quietly grows a second entry. `/api/queue` names "
     "what the machine is working on to anyone who asks, and the only thing "
     "stopping the set from growing is that somebody is counting it",
     [(EXEMPT_SET, EXEMPT_SET.replace('{"/api/health"}', '{"/api/health", "/api/queue"}'))]),

    ("R1", "under", RESEARCH,
     "⛔⛔ THE TWO MIDDLEWARES ARE SWAPPED. Starlette makes the LAST-added the "
     "OUTERMOST, so the gate ends up outside CORS and answers the browser's "
     "preflight — which carries no header to authenticate with. Every "
     "legitimate cross-origin call 401s before the origin policy ever runs, "
     "and the failure reads as a CORS bug",
     [(INSTALL, ""), (CORS_END, CORS_END + INSTALL)]),

    ("R2", "under", RESEARCH,
     "⛔⛔⛔ THE ONE LINE THE WAVE EXISTS FOR GOES BACK. `POST /api/runs` takes "
     "the Firebase identity FROM THE REQUEST BODY again, so whoever can reach "
     "the port chooses which account a run is written to and billed to",
     [(UID, '        uid = request_data.get("uid", "")')]),

    ("R3", "under", RESEARCH,
     "⛔⛔ a uid the caller named stops being refused and is silently replaced. "
     "The run goes to a different account than the caller asked for and the "
     "API reports success — somebody's work moved without anyone being told, "
     "which is worse than the bug it replaced",
     [(MISMATCH, "        if False:")]),

    ("R4", "under", RESEARCH,
     "⛔ the JSON coercion goes, so a `uid` that arrives as a dict or a list "
     "makes `.strip()` raise. A refusal turns into a 500 and the caller cannot "
     "tell a rejected identity from a broken server",
     [(COERCE, '        _claimed = (request_data.get("uid") or "").strip()')]),

    ("R5", "under", RESEARCH,
     "⛔⛔ THE GATE IS NOT INSTALLED AT ALL. Everything else still reads as "
     "done — the module is there, the token is minted, the banner names the "
     "file — and all fourteen routes are open",
     [(INSTALL, "")]),

    ("R6", "under", RESEARCH,
     "⛔ the boot-time mint goes. The middleware refuses everything because no "
     "token file exists, so a correctly-built gate locks the owner out of "
     "their own machine and the reason is nowhere on screen",
     [(MINT_AT_BOOT, "    try:\n        pass\n")]),

    ("R7", "under", RESEARCH,
     "⛔ `--help` starts advertising `WS /ws/{run_id}` again — a route deleted "
     "on 2026-04-29 that the reference table described for five months, "
     "because the only test asked whether the row reached the output rather "
     "than whether the route existed",
     [(REFERENCE_TAIL,
       REFERENCE_TAIL + '\n    ("WS   /ws/{run_id}",                   "Real-time event stream"),')]),

    ("R8", "under", RESEARCH,
     "⛔⛔ the boot banner prints the TOKEN instead of its path. Terminal "
     "scrollback is pasted into chats, screenshots and support bundles — this "
     "is the shape that put a live credential into a transcript once already "
     "today",
     [(BANNER_ROW,
       '        _token_row = [("API token", _c(_DIM, open(str(_srv_token_path())).read()))]')]),

    ("C1", "under", CONFTEST,
     "⛔⛔ the suite stops redirecting the token directory, so any test that "
     "reaches `ensure_token()` mints a LIVE credential into the developer's "
     "own `~/.super-research/` — beside the keystore a running backend is "
     "authenticating against",
     [(ISOLATION, "    pass")]),
    ("S13", "under", TOKEN,
     "⛔⛔ the decode guard narrows back to `except OSError`, so a token file "
     "that is not valid UTF-8 — Windows Notepad's legacy 'Unicode' save, a "
     "truncated restore — raises out of the middleware. Every request answers "
     "500 with a traceback instead of 401, while /api/health keeps answering "
     "200 so the watchdog reports a perfectly healthy worker",
     [(READ_GUARD, "    except OSError:")]),

    ("S14", "under", TOKEN,
     "⛔⛔ the comparison drops the encode. `compare_digest` on two `str` "
     "objects REQUIRES both to be ASCII-only and raises TypeError otherwise, so "
     "any header with a non-ASCII byte in it — which curl sends happily — "
     "becomes a 500. A refusal must never depend on what the refused caller "
     "sent",
     [(COMPARE, "    return hmac.compare_digest(presented, stored)")]),

    ("S15", "under", TOKEN,
     "⛔ the clear-and-remint goes, so a zero-byte token file left by a crash "
     "or a full disk bricks the machine permanently: every boot loses the "
     "create race to it and refuses everything, and nothing on screen points "
     "at a file anybody would think to delete",
     [(EMPTY_CLEAR, "    if False:\n        try:\n"
                    "            if path.exists() and not path.read_bytes().strip():")]),

    ("R9", "under", RESEARCH,
     "⛔⛔ the ENQUEUED payload re-reads the request body. Every line above it "
     "still says the identity comes from the pairing — the 403 is still there, "
     "the comment is still there — and the job the worker actually receives "
     "carries the caller's uid again. This is the shape a 'let the caller pick "
     "when it matches' feature would take",
     [(ENQUEUE, '"run_id": run_id, "uid": request_data.get("uid", uid), '
                '"brief_text": brief_text})')]),

    ("R10", "under", RESEARCH,
     "⛔ the DELETE row leaves the --help reference again. The one route that "
     "destroys data becomes invisible on the only surface that describes the "
     "API, which is exactly how two deleted routes stayed advertised for five "
     "months in the other direction",
     [(DELETE_ROW, "")]),
]


def _mark(mid: str, target: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{target}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _stranded() -> "str | None":
    if not _INFLIGHT.exists():
        return None
    return _INFLIGHT.read_text(encoding="utf-8").strip()


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def purge_pycache(root: Path) -> None:
    for d in root.rglob("__pycache__"):
        if ".venv" not in d.parts and "org-stage" not in d.parts:
            shutil.rmtree(d, ignore_errors=True)


def _digest() -> dict:
    return {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in FILES}


def _pytest() -> str:
    """'green' | 'red' | 'nothing-collected'."""
    purge_pycache(ROOT)
    args = [sys.executable, "-B", "-m", "pytest", *SUITES.split(),
            "-q", "-p", "no:cacheprovider"]
    code = sh(args, cwd=ROOT, env=ENV).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def run_tests() -> bool:
    got = _pytest()
    if got == "nothing-collected":
        raise AssertionError("the selection collected NO tests — check SUITES")
    return got == "green"


def main() -> int:
    only = {a.strip() for a in sys.argv[1:] if a.strip()}
    selected = [m for m in MUTANTS if not only or m[0] in only]

    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — spot check, not a score.")
    print("scope: both owned suites, unfiltered (see the module docstring)")

    if (s := _stranded()):
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {s}\nRestore it (git checkout -- <file>), then delete\n    {_INFLIGHT}")
        return 2

    before = _digest()
    print("baseline… ", end="", flush=True)
    try:
        if not run_tests():
            print("⛔ RED BEFORE ANY MUTANT — fix the tree first.")
            return 2
    except AssertionError as exc:
        print(f"⛔ BASELINE FAULT: {exc}")
        return 2
    print("green\n")

    survivors, faults, flaky = [], [], []
    for mid, direction, target, why, edits in selected:
        path = ROOT / target
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x in {target} (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            if mutated == original:
                raise AssertionError("the mutant is byte-identical to the original")
            try:
                compile(mutated, target, "exec")
            except SyntaxError as syn:
                raise AssertionError(
                    f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                    "check the anchor's indentation") from None
            _mark(mid, target)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            # ⛔⛔ A FLAP IS ITS OWN OUTCOME, NOT A SURVIVOR. On disagreement,
            # run a third time and take the majority — reported separately,
            # because "the guards cannot see this" and "that run was noisy" are
            # different claims.
            verdicts = [not run_tests() for _ in range(SURVIVOR_CONFIRMATIONS)]
            flapped = len(set(verdicts)) > 1
            if flapped:
                verdicts.append(not run_tests())
            killed = sum(verdicts) * 2 > len(verdicts)
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = (f"  ⚠ FLAPPED {sum(verdicts)}/{len(verdicts)} — tie broken by "
                    "majority" if flapped else "")
            print(f"{mark} {mid} [{direction}] ({target}) {why}{note}")
            if not killed:
                survivors.append((mid, direction, target, why))
            elif flapped:
                flaky.append((mid, sum(verdicts), len(verdicts)))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            faults.append((mid, direction, target, why, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    after = _digest()
    if (left := [f for f in before if before[f] != after[f]]):
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in left))
        return 3

    over = sum(1 for m in selected if m[1] == "over")
    label = " (SPOT CHECK)" if only else ""
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, _d, _t, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if flaky:
        print(f"⚠ {len(flaky)} FLAPPED and were resolved by majority — killed, "
              f"but this selection is not perfectly stable:")
        for mid, k, n in flaky:
            print(f"    {mid}: killed in {k} of {n} runs")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, target, why in survivors:
            print(f"    {mid} [{direction}] ({target}) {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
