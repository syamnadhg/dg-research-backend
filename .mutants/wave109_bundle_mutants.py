"""Wave 10.9 (#539 + #541b) — can the guards see a support bundle carrying
somebody else again?

⛔⛔ WHAT THE WAVE CLOSED. `_INDEX_PRIVATE_KEYS` kept the uid out of index.json
and out of nothing else. An owner's whole-machine bundle shipped every other
member's run folder whole — their uid in `meta.json` and in the run.log header,
their topic in the queue path — and the sessions and raw tails carried every
member's uid (`users/<uid>/`, `audio/<uid>/`, `o/logs%2F<uid>%2F…`,
`ownerUid='…'`, `submittedBy=<prefix>`) and topic (`topic='…'`,
`queues/<slug>_<ts>`, `run_id=<slug>_<ts>`). Measured in three real bundles.

⛔⛔ AND THE TEST THAT CLAIMED TO GUARD IT READ index.json ONLY (#541b), so it
stayed green with the uid sitting twice in the file next door.

Every mutant below is a way the fix could be put back to decoration while still
looking installed. The ones that matter most are the quiet ones:

  B2  — the other-members drop moves AFTER the count bound. Still present,
        still greppable; the owner's bundle is then "the newest N, minus
        everyone else's", which on a busy shared machine is nothing at all.
  B6  — a scoped bundle keeps the device OWNER instead of its requester, so a
        sharer's own run is dropped from the only bundle they may send.
  B8  — the owner's own run goes through the redactor. Looks like MORE
        protection; it strips the owner's own topic from their own run.
  B11 — the redactor is called and its result thrown away — the shape of a fix
        that reads as installed.
  B22 — the count reaches the logBundles row. The rules' `hasOnly` refuses the
        WHOLE write, so every bundle stalls at 'collecting' until a rules
        deploy — the over-correction a reviewer waves through as "reporting".
  R8  — the kept uid must match whole; the logs print `uid[:8]`, so the owner's
        own prefixes turn into `member-N` in their own bundle.
  R12 — the uid shape stops requiring a capital, so every 28-char hex digest
        becomes a "member".

⛔ ANCHORS ARE SINGLE STRING LITERALS AND MUST MATCH EXACTLY ONCE. A stale
anchor is a harness fault, not a survivor, and faults are counted OUT. Every
mutated file is COMPILED before it is written: a mutant that does not parse
fails every test and would report a kill for a reason unrelated to the tests.

⚠ RUN WITH THE INTERPRETER YOU WANT MEASURED. The tests run as
`sys.executable -m pytest` from the repo root, so `-m` puts this checkout first
on sys.path — which is what makes a worktree measure itself rather than the
editable install the venv points at.

  <venv>/bin/python -u .mutants/wave109_bundle_mutants.py
  <venv>/bin/python -u .mutants/wave109_bundle_mutants.py B2 B6
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = ("tests/test_bundle_other_members_109.py "
          "tests/test_bundle_selection_0824.py "
          "tests/test_run_log_capture_0818.py "
          "tests/test_send_logs_cli_0818.py "
          "tests/test_log_bundle_0818.py")
RESEARCH = "research.py"
FILES = (RESEARCH,)
ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

# ── anchors: research.py ────────────────────────────────────────────────────
#: The whole-machine drop, before the count bound.
SPLIT_WHOLE = "candidates, other_members = _split_other_members_runs(rows, own_uid)"
SELECT_WHOLE = "selected = _select_bundle_runs(candidates, max_runs=max_runs,"
SELECT_TAIL = ("                                       max_age_days=max_age_days, now=now)\n"
               "        selection_report = {}")
#: The drop after an explicit pick.
SPLIT_PICK = "selected, other_members = _split_other_members_runs(selected, own_uid)"
#: The split helper's one decision.
SPLIT_RULE = "        if uid and uid != keep:"
#: Whose identity the archive keeps.
OWN_UID = "own_uid = requester_uid if requester_uid is not None else keep_uid"
#: Verbatim-or-redacted, per run folder.
REDACT_RUN = 'redact_run = not (own_uid and row.get("submitterUid") == own_uid)'
#: Sessions always redacted.
SESSION_REDACT = 'f"sessions/{member.name}", True)'
#: Tails always redacted.
TAIL_REDACT = "            clean = redactor.data(data)"
#: The redacted writer's own call.
FILE_REDACT = "        data = redactor.data(raw)"
#: Which queues are the kept person's.
OWNED = "                      if own_uid and uid == own_uid])"
#: Where the redactor learns which uids exist.
KNOWN = 'known_uids=[r.get("submitterUid") for r in rows] + list(queue_owners.values()),'
#: The archive's mode.
CHMOD = "        os.chmod(str(dest), 0o600)"
OPEN_MODE = "os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)"
OPEN_CALL = "    with _open_private_bundle(dest) as fh, \\"
#: The callers.
DEVICE_KEEP = "                keep_uid=owner_uid)"
CLI_KEEP = "                                    keep_uid=load_paired_uid())"
#: Reporting.
COLLECTED_COUNT = '            "runsOtherMembers": other_members,'
SUMMARY_COUNT = '        "runsOtherMembers": other_members,\n        "sizeBytes"'
ROW_PATCH = ('                "runsApplied": int(summary["maxRunsApplied"]),\n'
             "            })\n"
             "            object_path")
CLI_SAY = "    if _n_others:"
#: The redactor's passes.
P_USERS = "        s = _BUNDLE_USERS_PATH_RE.sub("
P_KEYED = "        s = _BUNDLE_UID_KEY_RE.sub(self._keyed, s)"
P_KNOWN = "            s = self._known_re.sub(lambda m: self.swap(m.group(0)), s)"
P_SHAPE = "        return _BUNDLE_UID_SHAPE_RE.sub(lambda m: self.swap(m.group(0)), s)"
P_QUEUE = "        s = _BUNDLE_QUEUE_NAME_RE.sub(self._queue, s)"
P_TOPIC_Q = "        s = _BUNDLE_TOPIC_QUOTED_RE.sub("
P_TOPIC_B = "        s = _BUNDLE_TOPIC_BARE_RE.sub("
#: The redactor's decisions.
KEPT = "value == self.keep or (len(value) >= 6 and self.keep.startswith(value)))"
IDEMPOTENT = "if self._is_kept(value) or value in self._alias_names:"
PREFIX_KEY = "key = next((u for u in self._known if u.startswith(value)), value)"
SHAPE_CAPITAL = "(?=[A-Za-z0-9]*[A-Z])"
NOT_UUID = "(?<![Uu])(?:uid|Uid|UID)"
NON_VALUES = "        if value in _BUNDLE_UID_NON_VALUES:"
SHAPE_BOUNDARY = ('r"(?:(?<![A-Za-z0-9])|(?<=%2F)|(?<=%2f))"\n'
                  '    r"(?=[A-Za-z0-9]*[0-9])')
USERS_ENCODED = "(users(?:/|\\\\|%2F|%2f))"
DECODE = 'raw.decode("utf-8", "surrogateescape")'
QUEUE_OWNED = "return m.group(0) if m.group(0) in self.owned_queues else m.group(1)"
#: The queue-dir owner map.
MAP_GUARD = 'if isinstance(owner, dict) else ""'
MAP_WRITE = "            out[d.name] = uid"

MUTANTS = [
    # ══ which runs ship ═══════════════════════════════════════════════
    ("B1", "under", RESEARCH,
     "⛔⛔ THE DEFECT ITSELF — the whole-machine bundle carries every member's "
     "run folder again: their uid in meta.json and the run.log header, their "
     "topic in the queue path",
     [(SPLIT_WHOLE, "candidates, other_members = rows, 0")]),

    ("B2", "under", RESEARCH,
     "⛔⛔ the drop moves AFTER the count bound — the owner gets the newest N "
     "minus everyone else's, which on a busy shared machine is nothing",
     [(SELECT_WHOLE, "selected = _select_bundle_runs(rows, max_runs=max_runs,"),
      (SELECT_TAIL, "                                       max_age_days=max_age_days, now=now)\n"
                    "        selected, other_members = _split_other_members_runs(selected, own_uid)\n"
                    "        selection_report = {}")]),

    ("B3", "under", RESEARCH,
     "a foreign run ticked at the terminal (`--send-logs --select`) ships whole",
     [(SPLIT_PICK, "other_members = 0")]),

    ("B4", "under", RESEARCH,
     "⛔ an unpaired machine (no owner to keep) keeps EVERY member's run — the "
     "doubt resolves toward collecting more",
     [(SPLIT_RULE, "        if uid and keep and uid != keep:")]),

    ("B5", "over", RESEARCH,
     "⛔ unattributed runs are dropped too — that is every fleet run until the "
     "attributing wheel ships, so the owner's bundle loses its evidence",
     [(SPLIT_RULE, "        if uid != keep:")]),

    ("B6", "under", RESEARCH,
     "⛔⛔ a scoped bundle keeps the device OWNER, not its requester — a sharer's "
     "own run is dropped from the only bundle they may send",
     [(OWN_UID, "own_uid = keep_uid")]),

    # ══ which members are redacted ════════════════════════════════════
    ("B7", "under", RESEARCH,
     "⛔⛔ an unattributed run ships verbatim — its run.log header names whoever "
     "submitted it, and every fleet run is unattributed today",
     [(REDACT_RUN, "redact_run = False")]),

    ("B8", "over", RESEARCH,
     "the owner's own run goes through the redactor — reads as more protection, "
     "strips the owner's own topic from their own run",
     [(REDACT_RUN, "redact_run = True")]),

    ("B9", "under", RESEARCH,
     "sessions ship verbatim — pairing/serve sessions carry members' uids",
     [(SESSION_REDACT, 'f"sessions/{member.name}", False)')]),

    ("B10", "under", RESEARCH,
     "⛔ the raw tails ship verbatim — the superset of everything the machine "
     "ever did, for everyone who uses it",
     [(TAIL_REDACT, "            clean = data")]),

    ("B11", "under", RESEARCH,
     "⛔ the redactor's result is thrown away in the file writer — installed, "
     "greppable, and doing nothing",
     [(FILE_REDACT, "        data = raw")]),

    ("B12", "under", RESEARCH,
     "every queue counts as the owner's, so every member's topic slug stays",
     [(OWNED, "                      if own_uid])")]),

    ("B13", "over", RESEARCH,
     "no queue counts as the owner's — the owner.json proof is ignored and the "
     "owner's own queue names are stripped",
     [(OWNED, "                      if False])")]),

    ("B14", "under", RESEARCH,
     "the run metas stop teaching the redactor which uids exist, so a member's "
     "uid in a shape no pattern knows survives",
     [(KNOWN, "known_uids=list(queue_owners.values()),")]),

    ("B15", "under", RESEARCH,
     "the queue owners stop teaching the redactor which uids exist",
     [(KNOWN, 'known_uids=[r.get("submitterUid") for r in rows],')]),

    # ══ the archive's mode ═══════════════════════════════════════════
    ("B16", "under", RESEARCH,
     "an existing file keeps its 0644 — O_CREAT's mode only applies on create",
     [(CHMOD, "        pass")]),

    ("B17", "under", RESEARCH,
     "the archive is created 0644 — readable by every account on the computer",
     [(OPEN_MODE, "os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)")]),

    ("B18", "under", RESEARCH,
     "the archive is opened the old way, with the umask's mode",
     [(OPEN_CALL, '    with open(dest, "wb") as fh, \\')]),

    # ══ the callers ══════════════════════════════════════════════════
    ("B19", "under", RESEARCH,
     "⛔⛔ the device handler stops naming the owner — the builder keeps nobody "
     "and the owner's own runs vanish from their own bundle",
     [(DEVICE_KEEP, "                keep_uid=None)")]),

    ("B20", "under", RESEARCH,
     "⛔ the terminal stops naming the paired uid",
     [(CLI_KEEP, "                                    keep_uid=None)")]),

    # ══ reporting ════════════════════════════════════════════════════
    ("B21", "under", RESEARCH,
     "the zip stops saying how many runs were left out",
     [(COLLECTED_COUNT, '            "runsOtherMembers": 0,')]),

    ("B22", "over", RESEARCH,
     "⛔⛔ the count reaches the logBundles row before the rules allow it — the "
     "rules refuse the whole write and every bundle stalls at 'collecting'",
     [(ROW_PATCH, '                "runsApplied": int(summary["maxRunsApplied"]),\n'
                  '                "runsOtherMembers": int(summary["runsOtherMembers"]),\n'
                  "            })\n"
                  "            object_path")]),

    ("B23", "under", RESEARCH,
     "the terminal leaves runs out without a word",
     [(CLI_SAY, "    if False:")]),

    ("B24", "under", RESEARCH,
     "the builder's summary stops carrying the count, so the terminal can never "
     "say it",
     [(SUMMARY_COUNT, '        "sizeBytes"')]),

    # ══ the redactor's passes ════════════════════════════════════════
    ("R1", "under", RESEARCH,
     "a Firestore path keeps any uid the other rules miss",
     [(P_USERS, "        s = s or _BUNDLE_USERS_PATH_RE.sub(")]),

    ("R2", "under", RESEARCH,
     "`submittedBy=<prefix>` / `ownerUid='…'` survive",
     [(P_KEYED, "        s = s")]),

    ("R3", "under", RESEARCH,
     "a known uid in an unpatterned shape survives",
     [(P_KNOWN, "            s = s")]),

    ("R4", "under", RESEARCH,
     "⛔ a Firebase uid in an audio URL or a Storage object path survives",
     [(P_SHAPE, "        return s")]),

    ("R5", "under", RESEARCH,
     "⛔ `queues/<topic-slug>_<ts>` and `run_id=<topic-slug>_<ts>` keep the topic",
     [(P_QUEUE, "        s = s")]),

    ("R6", "under", RESEARCH,
     "`topic='…'` survives",
     [(P_TOPIC_Q, "        s = s or _BUNDLE_TOPIC_QUOTED_RE.sub(")]),

    ("R7", "under", RESEARCH,
     "a bare `topic=…` survives",
     [(P_TOPIC_B, "        s = s or _BUNDLE_TOPIC_BARE_RE.sub(")]),

    # ══ the redactor's decisions ═════════════════════════════════════
    ("R8", "over", RESEARCH,
     "the owner's printed `uid[:8]` prefixes become `member-N` in their own bundle",
     [(KEPT, "value == self.keep)")]),

    ("R9", "over", RESEARCH,
     "the owner's own uid is aliased everywhere",
     [(KEPT, "False)")]),

    ("R10", "over", RESEARCH,
     "an alias is re-aliased, so one person becomes two",
     [(IDEMPOTENT, "if self._is_kept(value):")]),

    ("R11", "over", RESEARCH,
     "a printed prefix of a known uid becomes a different member from the uid",
     [(PREFIX_KEY, "key = value")]),

    ("R12", "over", RESEARCH,
     "every 28-char hex digest becomes a 'member'",
     [(SHAPE_CAPITAL, "")]),

    ("R13", "over", RESEARCH,
     "`installUuid=` is treated as a person",
     [(NOT_UUID, "(?:uid|Uid|UID)")]),

    ("R14", "over", RESEARCH,
     "`uid=None` becomes `uid=member-1`",
     [(NON_VALUES, "        if False:")]),

    ("R15", "under", RESEARCH,
     "a uid inside a URL-encoded Storage path (`logs%2F<uid>%2F`) survives",
     [(SHAPE_BOUNDARY, 'r"(?<![A-Za-z0-9])"\n    r"(?=[A-Za-z0-9]*[0-9])')]),

    ("R16", "under", RESEARCH,
     "a URL-encoded Firestore path (`users%2F<uid>`) survives",
     [(USERS_ENCODED, "(users(?:/|\\\\))")]),

    ("R17", "over", RESEARCH,
     "a byte that is not UTF-8 is replaced, so the archive stops being the log",
     [(DECODE, 'raw.decode("utf-8", "replace")')]),

    ("R18", "over", RESEARCH,
     "the owner's own queue names lose their slug even with owner.json proving them",
     [(QUEUE_OWNED, "return m.group(1)")]),

    # ══ the queue-dir owner map ══════════════════════════════════════
    ("Q1", "over", RESEARCH,
     "an owner.json that is not an object crashes the whole bundle",
     [(MAP_GUARD, "")]),

    ("Q2", "under", RESEARCH,
     "the map is always empty, so no queue is ever the owner's",
     [(MAP_WRITE, "            pass")]),
]


def _run(cmd):
    return subprocess.run(cmd, cwd=ROOT, env=ENV, shell=True,
                          capture_output=True, text=True)


def green():
    r = _run(f"{sys.executable} -m pytest {SUITES} -q -x -p no:cacheprovider")
    out = (r.stdout or "") + (r.stderr or "")
    # ⛔ THE SUMMARY LINE, NEVER THE EXIT CODE. This repo's backend suite once
    # died at 27% and exited 0, and a commit rode on it.
    return " failed" not in out and " error" not in out and "passed" in out


# ⛔⛔ EVERYTHING BELOW RUNS UNDER `__main__` ONLY. The static anchor sweep loads
# every harness in this directory with `spec.loader.exec_module`, which
# EXECUTES it — an unguarded runner turns a seconds-long check into a full run.
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
            try:
                compile(mutated, fname, "exec")
            except SyntaxError as e:
                raise AssertionError(f"mutant does not parse: {e}")
            path.write_text(mutated, encoding="utf-8")
            if green():
                survivors.append(mid)
                print(f"  {mid}  ✗ SURVIVED ({direction}) — {why}", flush=True)
            else:
                print(f"  {mid}  ✓ killed", flush=True)
        except AssertionError as e:
            survivors.append(f"{mid} (anchor)")
            print(f"  {mid}  ⛔ HARNESS FAULT — {e}", flush=True)
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
