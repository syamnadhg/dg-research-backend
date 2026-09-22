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
  B22 — the count rides the 'uploading' write. Since W9 it belongs on the
        `done` write only, beside "Sent"; earlier, it states a fact about a
        bundle nothing has sent yet (re-aimed 2026-09-21 — it used to guard the
        row against the count entirely, before the rules allowed it).
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
#: The redacted writer follows the archive's compression setting.
FILE_COMPRESS = "        info.compress_type = zf.compression"
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
CLI_KEEP = "                                    keep_uid=_keep_uid)"
#: Reporting.
COLLECTED_COUNT = '            "runsOtherMembers": other_members,'
SUMMARY_COUNT = '        "runsOtherMembers": other_members,\n        "sizeBytes"'
ROW_PATCH = ('                "runsApplied": int(summary["maxRunsApplied"]),\n'
             "            })\n"
             "            object_path")
CLI_SAY = "    if _others_line:"
CLI_LINE = ('    _others_line = _send_logs_left_out_line(summary.get("runsOtherMembers"),'
            " _keep_uid)")
SAY_BLAME = ('    if keep_uid:\n'
             '        return f"{n} run(s) left out — another member ran them"')
#: The redactor's passes. ⛔ ONE LIST, ONE LINE EACH, and the order in it is
#: output: `member-N` is first-appearance order.
P_USERS = "            lambda t: _BUNDLE_USERS_PATH_RE.sub(self._users_path, t),"
P_KEYED = "            lambda t: _BUNDLE_UID_KEY_RE.sub(self._keyed, t),"
P_KNOWN = "            out.append(lambda t: self._known_re.sub(self._shaped, t))"
P_SHAPE = "        out.append(lambda t: _BUNDLE_UID_SHAPE_RE.sub(self._shaped, t))"
P_QUEUE = "            lambda t: _BUNDLE_QUEUE_NAME_RE.sub(self._queue, t),"
P_TOPIC_L = "            lambda t: _BUNDLE_TOPIC_LINE_RE.sub(self._topic_line, t),"
P_TOPIC_Q = "            lambda t: _BUNDLE_TOPIC_QUOTED_RE.sub(self._topic_quoted, t),"
P_TOPIC_B = (r'            lambda t: _BUNDLE_TOPIC_BARE_RE.sub(r"\1" + '
             "_BUNDLE_TOPIC_MARK, t),")
#: Chunking, and the loop order that keeps it invisible.
TEXT_LOOP = ("        for run in self._passes():\n"
             "            for i, piece in enumerate(pieces):\n"
             "                pieces[i] = run(piece)")
CHUNK_CUT = '        cut = s.find("\\n", start + size)'
#: The topic rules themselves.
TOPIC_Q_RE = (r'''    r"(?<![\w\-/])([\"']?topic[\"']?[ \t]*[=:]'''
              r'''|topic(?=[ \t]))([ \t]*)"''')
#: The bare alternative's space lookahead — what keeps `topic's` from reading as
#: a quoted value.
TOPIC_Q_POSSESSIVE = r'''|topic(?=[ \t]))([ \t]*)"'''
TOPIC_B_RE = (r'''    r"(?<![\w\-/])(topic[ \t]*[=:])(?![ \t]*['\"])[^\n]*?"''' "\n"
              r'''    r"(?=[ \t]+(?:" + _BUNDLE_TOPIC_END_KEYS + r")=|\n|$)",''')
#: Where a bare topic value is allowed to end.
TOPIC_B_TAIL = r'''    r"(?=[ \t]+(?:" + _BUNDLE_TOPIC_END_KEYS + r")=|\n|$)",'''
#: The three shapes the first pass missed, each named so `_topic_line` still
#: finds its groups when one is made unmatchable.
LINE_TERMS = r'''    r"(?P<terms>distinctive[ \t]+(?:terms|word\(s\))[ \t]*\()[^)\n]*"'''
LINE_CHATS = r'''    r"(?P<chats>top recent sidebar chats[ \t]*\[)[^\n]*(?P<chats_close>\])"'''
#: What may sit inside a quoted title: an apostrophe followed by a letter is
#: part of the title, because nothing escapes these values.
LINE_NAMED_VALUE = r'''    r"(?:(?!(?P=quote))[^\n]|(?P=quote)(?=[A-Za-z]))*(?P=quote)"'''
LINE_NAMED = (r'''    r"(?P<named>(?:generated title|opening owned sidebar chat'''
              r'''|sidebar entry)"''')
#: Whether the text is cut at all, and how small the bites are.
TEXT_CHUNK = "        pieces = _bundle_line_chunks(s, _BUNDLE_REDACT_CHUNK)"
CHUNK_SIZE = "_BUNDLE_REDACT_CHUNK = 1 << 20"
#: The machine-log call sites themselves — `_log_job_ref` is a helper, and a
#: helper is not a call site: all four of these could name the subject again
#: with the helper untouched.
SITE_QUEUED = '            log(f"Starting queued job {_log_job_ref(job)}")'
SITE_RENAME = '            log(f"Renaming notebook (smart title, {len(title)} chars)...")'
SITE_DOM_RENAME = ('            log(f"[{label}] DOM rename OK '
                   '(read-back verified, {len(title)} chars)")')
SITE_ORPHAN = ('            log(f"[idle-rescan] worker {WORKER_ID}: picking up orphan '
               "{research_id[:8]}… submittedBy={(d.get('submittedBy') or '?')[:8]}\")")
#: And the five round-2 ones.
SITE_SIDEBAR_LIST = '        log(f"[{label}] top {len(_titles)} recent sidebar chat(s) "'
SITE_SIDEBAR_OPEN = ('        log(f"[{label}] opening owned sidebar chat '
                     '#{_ci + 1}/{len(_owned)} "')
SITE_REFUSE = '                        log(f"[title-refresh] REFUSING the generated title "'
SITE_BRIEF_ANCHORS = ("""        f"distinctive terms ({', '.join(anchors[:6])}) """
                      '''— this is not a brief "''')
#: The two rules as they shipped in the first pass, for T2 / T3.
TOPIC_Q_OLD = r'''    r"(?<![\w-])(topic)(=|[ \t]+)"'''
TOPIC_B_OLD = r'''    r"(?<![\w-])(topic=)(?!['\"])[^\n]*?(?=[ \t]+[A-Za-z_]+=|\n|$)",'''
TOPIC_KEEP_QUOTES = ("        return m.group(1) + m.group(2) + quote + "
                     "_BUNDLE_TOPIC_MARK + quote")
TOPIC_ORPHAN = "                return opener + _BUNDLE_TOPIC_MARK + m.group(close_name)"
#: What a machine-wide log line may name instead of a topic.
REF_RID = '    research_id = str(job.get("research_id") or "").strip()'
REF_STAMP = '            return "queue " + stamp.group(1)'
#: The redactor's decisions.
KEPT = "value == self.keep or (len(value) >= 6 and self.keep.startswith(value)))"
IDEMPOTENT = "if self._is_kept(value) or value in self._alias_names:"
PREFIX_KEY = "key = next((u for u in self._known if u.startswith(value)), value)"
SHAPE_CAPITAL = "(?=[A-Za-z0-9]*[A-Z])"
SHAPE_CLASSES = r'    r"(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z])"'
NOT_UUID = "(?<![Uu])(?:uid|Uid|UID)"
NON_VALUES = "        if value in _BUNDLE_UID_NON_VALUES:"
SHAPE_BOUNDARY = ('r"(?:(?<![A-Za-z0-9])|(?<=%2F)|(?<=%2f))"\n'
                  '    r"(?=[A-Za-z0-9]*[a-z])')
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

    ("B25", "under", RESEARCH,
     "redacted files are stored uncompressed — every unattributed run and "
     "every session, i.e. most of a fleet bundle",
     [(FILE_COMPRESS, "        info.compress_type = _zipfile.ZIP_STORED")]),

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

    # ⚠ RE-AIMED 2026-09-21 (wave 10.9, W9): the count now reaches the `done`
    # write ON PURPOSE, beside the rules that allow it. What stays wrong is it
    # riding the `uploading` write — a fact about a sent bundle, stated before
    # anything was sent, on the write a failed send never finishes.
    ("B22", "over", RESEARCH,
     "⛔ the count rides the 'uploading' write too — a claim about a sent bundle "
     "made before the upload, on a row a failed send leaves standing",
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
     [(P_USERS, "            lambda t: t,")]),

    ("R2", "under", RESEARCH,
     "`submittedBy=<prefix>` / `ownerUid='…'` survive",
     [(P_KEYED, "            lambda t: t,")]),

    ("R3", "under", RESEARCH,
     "a known uid in an unpatterned shape survives",
     [(P_KNOWN, "            pass")]),

    ("R4", "under", RESEARCH,
     "⛔ a Firebase uid in an audio URL or a Storage object path survives",
     [(P_SHAPE, "        pass")]),

    ("R5", "under", RESEARCH,
     "⛔ `queues/<topic-slug>_<ts>` and `run_id=<topic-slug>_<ts>` keep the topic",
     [(P_QUEUE, "            lambda t: t,")]),

    ("R6", "under", RESEARCH,
     "`topic='…'` survives",
     [(P_TOPIC_Q, "            lambda t: t,")]),

    ("R7", "under", RESEARCH,
     "a bare `topic=…` survives",
     [(P_TOPIC_B, "            lambda t: t,")]),

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
     [(SHAPE_BOUNDARY, 'r"(?<![A-Za-z0-9])"\n    r"(?=[A-Za-z0-9]*[a-z])')]),

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

    # ══ the repair (cross-verify round 1) ════════════════════════════
    # ⛔⛔ THE FIRST PASS SHIPPED WITH THE TOPIC STILL IN THE TAILS. The redactor
    # knew `topic=` and `topic '…'`, and the lines this program actually writes
    # carry the subject with no key at all — measured in the owner's own
    # backend*.log, 9 of 9 queued-job pickups, 1 of 1 orphan claims and 5 of 5
    # notebook renames came through a bundle unchanged. The four source lines no
    # longer carry it AND the redactor now knows the shapes, because a tail is
    # fourteen days deep.
    ("T1", "under", RESEARCH,
     "⛔⛔ the lines with no `topic=` key ship their subject again — `Starting "
     "queued job: <topic>`, the orphan claim, both notebook renames",
     [(P_TOPIC_L, "            lambda t: t,")]),

    ("T2", "under", RESEARCH,
     "⛔ the quoted rule goes back to knowing only `topic=` and `topic '…'`, so "
     "an unattributed run.log's JSON and repr topics ship",
     [(TOPIC_Q_RE, TOPIC_Q_OLD)]),

    ("T3", "under", RESEARCH,
     "the bare rule goes back to `topic=` only, so `Topic: …` and `topic: …` ship",
     [(TOPIC_B_RE, TOPIC_B_OLD)]),

    ("T4", "over", RESEARCH,
     "the quotes come off a redacted value — reads as tidier, and a run.log or "
     "meta.json line that was JSON stops parsing for whoever opens the archive",
     [(TOPIC_KEEP_QUOTES,
       "        return m.group(1) + m.group(2) + _BUNDLE_TOPIC_MARK")]),

    ("T5", "under", RESEARCH,
     "every bracketed shape keeps its subject — the idle-rescan claim, the "
     "distinctive terms, the sidebar list — the line is matched and handed back",
     [(TOPIC_ORPHAN, "                return m.group(0)")]),

    ("T6", "under", RESEARCH,
     "⛔ the pickup line names the TOPIC again at the source — the shape that "
     "put every member's subject in the owner's machine log",
     [(REF_RID, '    research_id = str(job.get("topic") or "").strip()')]),

    ("T7", "under", RESEARCH,
     "the reference falls back to the whole `run_id`, which is "
     "`safe_name(topic)_<stamp>` — the subject back in another spelling",
     [(REF_STAMP, '            return "queue " + stamp.string')]),

    ("U1", "under", RESEARCH,
     "⛔ the uid shape demands a digit again — about one uid in a hundred and "
     "fifty has none, and a member whose folders have aged out is known by "
     "shape alone",
     [(SHAPE_CLASSES, '    r"(?=[A-Za-z0-9]*[0-9])(?=[A-Za-z0-9]*[a-z])'
                      '(?=[A-Za-z0-9]*[A-Z])"')]),

    ("C1", "under", RESEARCH,
     "⛔⛔ the chunk loop turns inside out — every pass on piece 1 before piece "
     "2 — so `member-N` is handed out in a different order and the same person "
     "is a different pseudonym than the whole-string redactor gives them",
     [(TEXT_LOOP, "        passes = self._passes()\n"
                  "        for i, piece in enumerate(pieces):\n"
                  "            for run in passes:\n"
                  "                piece = run(piece)\n"
                  "            pieces[i] = piece")]),

    ("C2", "under", RESEARCH,
     "⛔⛔ a chunk ends wherever the count runs out instead of after a newline, "
     "so a uid cut in half ships in two halves",
     [(CHUNK_CUT, "        cut = start + size")]),

    ("B26", "under", RESEARCH,
     "⛔⛔ the `own_uid and` guard goes, so on an unpaired machine `None == "
     "None` marks every unattributed folder as the kept person's own and it "
     "ships verbatim — which is the terminal's `--send-logs` there",
     [(REDACT_RUN, 'redact_run = not (row.get("submitterUid") == own_uid)')]),

    ("M1", "under", RESEARCH,
     "the terminal blames another member however the machine is paired",
     [(SAY_BLAME, '    if True:\n'
                  '        return f"{n} run(s) left out — another member ran them"')]),

    ("M2", "over", RESEARCH,
     "the terminal says 'not paired' on a paired machine — the honest sentence "
     "aimed at the wrong half",
     [(CLI_LINE, '    _others_line = _send_logs_left_out_line('
                 'summary.get("runsOtherMembers"), None)')]),

    # ══ the repair (cross-verify round 2) ════════════════════════════
    # ⛔⛔ THE FIRST REPAIR RE-CHECKED ITSELF WITH ITS OWN RULES, which can only
    # see the shapes the rules already know. Five more were shipping the whole
    # time — measured in this owner's LIVE backend.log, 148 characters of
    # another member's research subject in the tail that goes to support.
    ("V1", "under", RESEARCH,
     "⛔⛔ the off-topic diagnostics ship the topic's own distinctive words "
     "again — `distinctive terms (<the subject's words>)`, which have no key",
     [(LINE_TERMS,
       r'''    r"(?P<terms>distinctive[ \t]+(?:termsNEVER)[ \t]*\()[^)\n]*"''')]),

    ("V2", "under", RESEARCH,
     "Gemini's sidebar probe ships the list of other members' chat titles",
     [(LINE_CHATS, r'''    r"(?P<chats>top recent sidebar chatsNEVER[ \t]*\[)'''
                   r'''[^\]\n]*(?P<chats_close>\])"''')]),

    ("V3", "under", RESEARCH,
     "⛔⛔ the adopted chat title and the refused generated title ship — the two "
     "shapes measured surviving in the owner's live log",
     [(LINE_NAMED, r'''    r"(?P<named>(?:generated titleNEVER)"''')]),

    ("V16", "under", RESEARCH,
     "⛔ a chat title with an apostrophe in it closes its own quoted value, so "
     "`opening owned sidebar chat 'Bobs' divorce'` ships everything after the "
     "first apostrophe — and nothing escapes these values",
     [(LINE_NAMED_VALUE, r'''    r"[^'\"\n]*(?P=quote)"''')]),

    ("V4", "over", RESEARCH,
     "⛔ the bare `topic` alternative reads the possessive in `topic's` as an "
     "opening quote again and deletes the diagnostic to the next apostrophe",
     [(TOPIC_Q_POSSESSIVE, r'''|topic)([ \t]*)"''')]),

    ("V5", "under", RESEARCH,
     "a bare topic value ends at any `word=` again, so a subject with an equals "
     "sign in it — a formula, `p=np` — keeps its tail",
     [(TOPIC_B_TAIL, r'''    r"(?=[ \t]+[A-Za-z_]+=|\n|$)",''')]),

    # ⛔ THE SOURCE HALF. The redactor is the fourteen-day backstop; these are
    # the lines, and a subject put back in a spelling the backstop does not know
    # goes straight to support.
    ("V6", "under", RESEARCH,
     "the queued-job pickup names the topic again AT THE CALL SITE — the helper "
     "is untouched, so nothing that watches the helper can see it",
     [(SITE_QUEUED, """            log(f"Starting queued job {job.get('topic')}")""")]),

    ("V7", "under", RESEARCH,
     "the notebook rename prints the smart title, which IS the topic",
     [(SITE_RENAME, '            log(f"Renaming notebook - {title}...")')]),

    ("V8", "under", RESEARCH,
     "the DOM rename read-back prints the title behind a `title=` key, which no "
     "redaction rule knows",
     [(SITE_DOM_RENAME,
       '            log(f"[{label}] DOM rename OK (read-back verified, title={title})")')]),

    ("V9", "under", RESEARCH,
     "the idle-rescan orphan claim carries the subject again",
     [(SITE_ORPHAN,
       '            log(f"[idle-rescan] worker {WORKER_ID}: picking up orphan '
       "{research_id[:8]}… for {d.get('topic')} "
       "submittedBy={(d.get('submittedBy') or '?')[:8]}\")")]),

    ("V10", "under", RESEARCH,
     "Gemini's sidebar probe prints the titles themselves again",
     [(SITE_SIDEBAR_LIST,
       '        log(f"[{label}] top {_titles} recent sidebar chat(s) "')]),

    ("V11", "under", RESEARCH,
     "the adoption line prints the chat title it is opening",
     [(SITE_SIDEBAR_OPEN,
       '        log(f"[{label}] opening owned sidebar chat {_cand_title} "')]),

    ("V12", "under", RESEARCH,
     "the title-refresh refusal prints the generated title again",
     [(SITE_REFUSE,
       '                        log(f"[title-refresh] REFUSING the generated '
       'title {text} "')]),

    ("V13", "under", RESEARCH,
     "⛔ the Phase 1 brief gate keeps naming the topic's distinctive words — "
     "which it is meant to — but in a spelling `distinctive terms (…)` cannot "
     "see, so the bundle stops taking them out",
     [(SITE_BRIEF_ANCHORS,
       """        f"never mentions {', '.join(anchors[:6])} """
       '''— this is not a brief "''')]),

    # ⛔⛔ AND THE CHUNKING, whose only tests monkeypatched the size and
    # compared chunked to whole — identical paths when there is no chunking.
    ("V14", "under", RESEARCH,
     "⛔⛔ the text is not cut at all — one `re.sub` over a capped 32 MB run.log "
     "holds the GIL for seconds, eight passes deep, beside a live pipeline",
     [(TEXT_CHUNK, "        pieces = [s]")]),

    ("V15", "under", RESEARCH,
     "the bite is bigger than any log that can ship, so the cutting is inert "
     "while every test that monkeypatches the size stays green",
     [(CHUNK_SIZE, "_BUNDLE_REDACT_CHUNK = 1 << 40")]),
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
