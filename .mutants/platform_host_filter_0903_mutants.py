"""#277 — one host filter, and the nine copies that each got it wrong.

⛔⛔ THE FILTER WRITTEN TO SKIP THE PLATFORM'S OWN PAGES WAS DELETING THE RUN'S
SOURCES. Every scrape site asked `h.includes('chatgpt.com')` of the WHOLE URL, and
ChatGPT appends `?utm_source=chatgpt.com` to every outbound link it renders — so
the test matched on the tracking tag of genuine sources. Measured on the 6 August
capture: 22 of 40 anchors dropped, 16 sources reported where 36 existed. That was
diagnosed then and repaired at ONE of the ten sites; the other nine kept it.

⛔⛔ AND WRONG IN THE OTHER DIRECTION, WHICH IS THE LINK THE OWNER ASKED ABOUT.
The Python readers used `host in _HOST_DENYLIST` — an equality test — so
`support.anthropic.com` is not `anthropic.com` and an Anthropic support page was
presented as a research source.

⭐ THE SHARPEST ONES HERE:
  J3 — the host extraction goes and the guard tests the whole URL again. This is
       the 6 August defect exactly: every source ChatGPT tagged is discarded, the
       run reports a fraction of its citations, and nothing errors.
  J2 — the label boundary goes, so the anchored test becomes a bare suffix and
       `notchatgpt.com` is swallowed. The over-correction of J3, and the reason
       the pattern is `(^|\\.)` rather than something shorter.
  P1 — the Python rule goes back to equality, and every subdomain of every listed
       host is a source again — including the one the owner reported.
  W2 — the filter moves into `_sweep_source_urls`, which sounds tidier and is
       destructive: that list is capped and never revisited, so a wrong host rule
       there loses a real citation with no way to notice.
  L1 — `accounts.google.com` leaves the list. It came from the Gemini panel
       scrape, the only reader that ever excluded the sign-in host, and dropping
       it is what consolidating ten copies into one would quietly have done.

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale anchor
is a harness fault, not a survivor, and faults are counted OUT.

  .venv/bin/python .mutants/platform_host_filter_0903_mutants.py
  .venv/bin/python .mutants/platform_host_filter_0903_mutants.py --unfiltered
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_platform_host_filter_0903.py "
          "tests/test_panel_counts_9614.py")

MINE = ("listed_host or subdomain_is_platform or everything_else_survives or "
        "url_face_agrees or apps_list_host_for_host or bare_vendor_domain or "
        "ordinary_sources_survive or "
        "url_face_agrees or tracking_tag or turn_sweep or "
        "findings_list_now_agree or writer_applies or live_code_reader or "
        "every_scrape_site or panel_regex_is_built or whole_url or "
        "membership_in_the_denylist or read_in_exactly_two")

# ⛔⛔ EXACT COVERAGE, NOT A COUNT. A filter that silently deselects the guard
# written to kill a mutant reports that mutant as a SURVIVOR, which reads
# identically to a real one.
OWNED_FILES = ("tests/test_platform_host_filter_0903.py",)

TARGET = "research.py"
FILES = (TARGET,)
SURVIVOR_CONFIRMATIONS = 2
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
_INFLIGHT = Path(__file__).with_suffix(".inflight")

# ── anchors ─────────────────────────────────────────────────────────────
#: The generated predicate as it appears in the file (these JS strings are
#: ordinary Python literals, so every backslash is doubled).
#:
#: ⛔⛔ READ FROM THE SOURCE, NOT RETYPED. The first version hard-coded the host
#: alternation here, and the owner's 2026-09-03 narrowing — dropping the bare
#: `openai.com` / `anthropic.com` so a run researching those companies keeps its
#: citations — broke SIX anchors at once. A harness that spells the list a second
#: time is a second copy of the thing this whole fix exists to have one of, and a
#: stale anchor measures nothing while looking like a pass.
_HOST_RE = re.compile(r"/\(\^\|\\\\\.\)\(([^)]+)\)\$/i\.test\(String\(")
_ALT = _HOST_RE.search((ROOT / "research.py").read_text(encoding="utf-8")).group(1)
_G = ("/(^|\\\\.)(" + _ALT + ")$/i.test(String(%s||'').replace(/^https?:\\\\/\\\\//i,'')"
      ".split(/[\\\\/?#]/)[0].toLowerCase().replace(/:\\\\d+$/,'')"
      ".replace(/^www\\\\./,''))")

#: The inline-activity turn sweep — the one site a behaviour test can execute.
TURN = ("        if (%s) return;\n"
        "        if (seenUrl.has(h)) return;") % (_G % "h")
#: The Claude report sweep — the path the owner's support link came down.
CLAUDE = ("                    if (h && h.length < 500 && !%s && !seen.has(h)) {"
          % (_G % "h"))
PYRULE = '    return any(h == d or h.endswith("." + d) for d in _HOST_DENYLIST)'
WRITER = ("            urls = [u for u in _sweep_source_urls(content) "
          "if not _find_is_platform_host(u)]")
SWEEP = ("    return [\n"
         "        _find_trim_trailing_punct(raw)\n"
         "        for raw in _FIND_BARE_URL_RE.findall(_mask_code(md))\n"
         "    ]")
LIST = '    "accounts.google.com",     # sign-in\n})'

MUTANTS = [
    # ═════════ J — the page scrapes ══════════════════════════════════════════
    ("J3", "under",
     "⛔⛔ the host extraction goes and the guard tests the WHOLE URL again — the "
     "6 August defect exactly. ChatGPT tags every outbound link with "
     "`?utm_source=chatgpt.com`, so every genuine source matches the platform test "
     "and is discarded; 22 of 40 anchors went this way and nothing errored",
     [(TURN, TURN.replace(".split(/[\\\\/?#]/)[0]", ""))]),
    ("J2", "over",
     "⛔ the label boundary goes, so an anchored host test becomes a bare suffix "
     "and `notchatgpt.com` is swallowed with `chatgpt.com` — the over-correction of "
     "J3, and the reason the pattern is not written shorter",
     [(TURN, TURN.replace("/(^|\\\\.)(", "/("))]),
    ("J1", "under",
     "⛔⛔ one site reverts to the substring spelling. It reads exactly like a "
     "filter that skips the platform's own pages, which is why nine of them "
     "survived a month after the tenth was fixed",
     [(TURN, "        if (h.includes('chatgpt.com') || h.includes('openai.com') ||\n"
             "            h.includes('oaiusercontent') || h.includes('chat.openai')) return;\n"
             "        if (seenUrl.has(h)) return;")]),
    ("J4", "under",
     "⛔ the CLAUDE sweep alone reverts — the path the owner's support link came "
     "down. Eight sites still correct is what makes a missed ninth invisible",
     [(CLAUDE, "                    if (h && h.length < 500 && !h.includes('claude.ai') &&\n"
               "                        !h.includes('anthropic.com') && !seen.has(h)) {")]),

    # ═════════ P — the Python rule ═══════════════════════════════════════════
    ("P1", "under",
     "⛔⛔ the rule goes back to equality, so every subdomain of every listed host "
     "is a research source again — `support.anthropic.com`, `cdn.openai.com`, "
     "`files.oaiusercontent.com`. This is the owner's link, restored",
     [(PYRULE, "    return h in _HOST_DENYLIST")]),
    ("P2", "over",
     "⛔ the dot goes from the boundary, so a bare suffix test drops `myclaude.ai` "
     "and `notchatgpt.com` — real sources deleted to catch fake ones, which the "
     "read side is explicitly not allowed to trade",
     [(PYRULE, '    return any(h == d or h.endswith(d) for d in _HOST_DENYLIST)')]),
    ("P3", "over",
     "the rule becomes a substring test, so `openai.com.evil.example` is treated as "
     "the platform — a host list has to be anchored at the END or it names a prefix",
     [(PYRULE, '    return any(d in h for d in _HOST_DENYLIST)')]),

    # ═════════ W — which side judges the host ════════════════════════════════
    ("W1", "under",
     "⛔⛔ the writer stops filtering, so the Sources list and the Findings list "
     "answer differently about the same URL in the same run — one says the page is "
     "a source, the other says it is not",
     [(WRITER, "            urls = _sweep_source_urls(content)")]),
    ("W2", "over",
     "⛔⛔ the filter moves INTO the sweep, which sounds tidier and is destructive: "
     "that list is capped and never revisited, so the moment the host rule is wrong "
     "once a real citation is gone with nothing to notice it",
     [(WRITER, "            urls = _sweep_source_urls(content)"),
      (SWEEP, "    return [\n"
              "        _find_trim_trailing_punct(raw)\n"
              "        for raw in _FIND_BARE_URL_RE.findall(_mask_code(md))\n"
              "        if not _find_is_platform_host(_find_trim_trailing_punct(raw))\n"
              "    ]")]),

    # ═════════ L — the list itself ═══════════════════════════════════════════
    ("L2", "over",
     "⛔⛔ the three Google agent hosts collapse into `google.com`. It reads like "
     "tidying and it deletes every Google-hosted citation a report makes — "
     "Scholar, Books, Patents, Cloud docs. This mutant SURVIVED the first run on "
     "both sides of the app, which is how it earned its test",
     [('    "gemini.google.com",\n'
       '    "bard.google.com",\n'
       '    "notebooklm.google.com",\n'
       '    "notebook.google.com",',
       '    "google.com",')]),
    ("V1", "over",
     "⛔⛔ THE BARE VENDOR DOMAINS COME BACK. `openai.com` and `anthropic.com` on "
     "the list drop `anthropic.com/research/…`, `openai.com/index/…`, "
     "`docs.anthropic.com` and `platform.openai.com` — the vendors' own published "
     "research, announcements and API documentation. A run whose TOPIC is one of "
     "these companies, or LLMs at all, loses the citations most worth having, and "
     "it reads as tidying: two entries instead of five. The rule is 'this page is "
     "the agent talking to itself', not 'this company made the agent'",
     [('    "support.anthropic.com",   # \u26d4 the help-centre page the owner found in Sources\n'
       '    "console.anthropic.com",   # the API console UI',
       '    "anthropic.com",'),
      ('    "chat.openai.com",         # the previous product host\n'
       '    "auth.openai.com",         # sign-in \u2014 already named as chrome in `login_hosts`\n'
       '    "help.openai.com",         # help centre\n'
       '    "cdn.openai.com",          # asset CDN',
       '    "openai.com",')]),
    ("V2", "under",
     "\u26d4 the help centre leaves the list while the console stays, so the exact "
     "page the owner found in a Sources list is a research source again \u2014 the "
     "narrowing overshooting by one host",
     [('    "support.anthropic.com",   # \u26d4 the help-centre page the owner found in Sources\n', "")]),

    ("L1", "under",
     "⛔⛔ `accounts.google.com` leaves the list. It came from the Gemini panel "
     "scrape — the ONE reader that had ever excluded the sign-in host — and losing "
     "it is exactly what folding ten copies into one does when nobody checks what "
     "each copy knew that the others did not",
     [(LIST, "})")]),
]


def _mark(mid: str) -> None:
    _INFLIGHT.write_text(f"{mid}\t{TARGET}\n", encoding="utf-8")


def _unmark() -> None:
    try:
        _INFLIGHT.unlink()
    except FileNotFoundError:
        pass


def _stranded() -> str | None:
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


def _pytest(kfilter: str | None) -> str:
    """'green' | 'red' | 'nothing-collected'."""
    purge_pycache(ROOT)
    args = [sys.executable, "-B", "-m", "pytest", *SUITES.split(),
            "-q", "-p", "no:cacheprovider"]
    if kfilter:
        args += ["-k", kfilter]
    code = sh(args, cwd=ROOT, env=ENV).returncode
    if code == 5:
        return "nothing-collected"
    return "green" if code == 0 else "red"


def run_tests(kfilter: str | None) -> bool:
    got = _pytest(kfilter)
    if got == "nothing-collected":
        raise AssertionError("the selection collected NO tests — check the filter")
    return got == "green"


def _collected(files, kfilter: str | None) -> set:
    args = [sys.executable, "-B", "-m", "pytest", *files,
            "--collect-only", "-q", "-p", "no:cacheprovider"]
    if kfilter:
        args += ["-k", kfilter]
    out = sh(args, cwd=ROOT, env=ENV).stdout
    return {ln.strip() for ln in out.splitlines() if "::" in ln and not ln.startswith(" ")}


def _filter_misses(kfilter: str) -> set:
    return _collected(OWNED_FILES, None) - _collected(OWNED_FILES, kfilter)


def main() -> int:
    argv = [a.strip() for a in sys.argv[1:] if a.strip()]
    unfiltered = "--unfiltered" in argv
    only = {a for a in argv if a != "--unfiltered"}
    selected = [m for m in MUTANTS if not only or m[0] in only]
    kfilter = None if unfiltered else MINE

    if only:
        unknown = only - {m[0] for m in MUTANTS}
        if unknown:
            print(f"no such mutant: {', '.join(sorted(unknown))}")
            return 2
        print(f"⚠ FILTERED to {', '.join(sorted(only))} — spot check, not a score.")
    print("scope: THE WHOLE SELECTION (--unfiltered)" if unfiltered
          else "scope: THIS STEP'S OWN GUARDS (-k) — pass --unfiltered for the other number")

    if (s := _stranded()):
        print("⛔⛔ A PREVIOUS RUN DIED WITH A MUTANT IN THE SOURCE:\n"
              f"    {s}\nRestore it (git checkout -- {TARGET}), then delete\n    {_INFLIGHT}")
        return 2

    if kfilter:
        missed = _filter_misses(kfilter)
        total = len(_collected(OWNED_FILES, None))
        print(f"filter covers {total - len(missed)}/{total} of this step's own tests")
        if missed:
            print("⛔⛔ THE FILTER CANNOT SEE SOME OF THIS STEP'S OWN GUARDS, so "
                  "any mutant only they could kill would report as a SURVIVOR:")
            for tid in sorted(missed):
                print(f"    {tid}")
            return 2

    before = _digest()
    print("baseline… ", end="", flush=True)
    try:
        if not run_tests(kfilter) or not run_tests(None):
            print("⛔ RED BEFORE ANY MUTANT — fix the tree first.")
            return 2
    except AssertionError as exc:
        print(f"⛔ BASELINE FAULT: {exc}")
        return 2
    print("green (filtered and whole)\n")

    path = ROOT / TARGET
    survivors, faults, flaky = [], [], []
    for mid, direction, why, edits in selected:
        original = path.read_text(encoding="utf-8")
        try:
            mutated = original
            for frm, to in edits:
                if frm == to:
                    raise AssertionError("replacement is identical to the anchor")
                hits = mutated.count(frm)
                if hits != 1:
                    raise AssertionError(
                        f"anchor occurs {hits}x (needs exactly 1): {frm[:70]!r}")
                mutated = mutated.replace(frm, to, 1)
            if mutated == original:
                raise AssertionError("the mutant is byte-identical to the original")
            try:
                compile(mutated, TARGET, "exec")
            except SyntaxError as syn:
                raise AssertionError(
                    f"the mutant does not parse ({syn.lineno}: {syn.msg}) — "
                    "check the anchor's indentation") from None
            _mark(mid)
            path.write_text(mutated, encoding="utf-8")
            if path.read_text(encoding="utf-8") != mutated:
                raise AssertionError("the mutation did not reach the file")
            # ⛔⛔ A FLAP IS ITS OWN OUTCOME, NOT A SURVIVOR. On disagreement,
            # run a third time and take the majority — reported separately,
            # because "the guards cannot see this" and "that run was noisy" are
            # different claims and collapsing them sends the next reader hunting
            # a defect that is not there.
            verdicts = [not run_tests(kfilter) for _ in range(SURVIVOR_CONFIRMATIONS)]
            flapped = len(set(verdicts)) > 1
            if flapped:
                verdicts.append(not run_tests(kfilter))
            killed = sum(verdicts) * 2 > len(verdicts)
            mark = "✓ killed  " if killed else "✗ SURVIVED"
            note = (f"  ⚠ FLAPPED {sum(verdicts)}/{len(verdicts)} — tie broken by "
                    "majority" if flapped else "")
            print(f"{mark} {mid} [{direction}] {why}{note}")
            if not killed:
                survivors.append((mid, direction, why))
            elif flapped:
                flaky.append((mid, sum(verdicts), len(verdicts)))
        except AssertionError as exc:
            print(f"! ERROR    {mid} {exc}")
            faults.append((mid, direction, why, str(exc)))
        finally:
            path.write_text(original, encoding="utf-8")
            _unmark()

    after = _digest()
    if (left := [f for f in before if before[f] != after[f]]):
        print("\n⛔ THE TREE DID NOT COME BACK CLEAN — a mutant is still in your "
              "source:\n" + "\n".join(f"    {f}" for f in left))
        return 3

    over = sum(1 for m in selected if m[1] == "over")
    scope = " [whole selection]" if unfiltered else " [own guards]"
    label = " (SPOT CHECK)" if only else ""
    measured = len(selected) - len(faults)
    print(f"\n{measured - len(survivors)}/{measured} killed "
          f"({over} over-corrections){scope}{label}")
    if faults:
        print(f"⚠ {len(faults)} HARNESS FAULT(S) — measured nothing, counted out:")
        for mid, _d, _w, exc in faults:
            print(f"    {mid}: {exc}")
    if flaky:
        print(f"⚠ {len(flaky)} FLAPPED and were resolved by majority — killed, "
              f"but this selection is not perfectly stable:")
        for mid, k, n in flaky:
            print(f"    {mid}: killed in {k} of {n} runs")
    if survivors:
        print("SURVIVORS:")
        for mid, direction, why in survivors:
            print(f"    {mid} [{direction}] {why}")
    return 1 if (survivors or faults) else 0


if __name__ == "__main__":
    raise SystemExit(main())
