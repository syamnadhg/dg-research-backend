"""Wave 8, verify tail — the machine's own log says what it actually built.

⛔⛔ THE GAP THIS CLOSES, found while verifying a real field bundle. The archive's
summary carries eleven facts: how many runs went in, how many the machine holds,
sessions, whether the machine-level material was included, compressed and raw
bytes, the cap applied, whether a selection was honoured, and three separate
counts of runs that were asked for and not delivered. Every one of them was
written to Firestore. The machine's own log said `received` and `bundle uploaded
(N bytes)`.

So the FIRST artefact a support engineer opens — the log the person just sent —
was the only place that could not say what was in the archive next to it. And the
Firestore row is not a substitute: reading it needs console access to the
reporter's own tree, which is exactly what somebody triaging an attachment by
email does not have.

⭐ THE CLEAN CASE STAYS SHORT. Only counts that always carry information are
unconditional. Requested-vs-delivered, over-cap, dropped and refused appear only
when non-zero — this project's own log-noise finding applied to its newest log
line instead of discovered on it a month later.

⛔ APP-TRIGGERED PATH ONLY, and measured rather than assumed. `log()` prints AND
writes through; a serve worker's stdout is redirected into `backend.log`, which is
what carries this line into the NEXT bundle. A terminal `--send-logs` has nothing
armed and its stdout is the terminal, so the same call there would print an
unstyled line under the pretty summary and persist nothing.
"""
import pytest

import research

CODE = "7QK4M2XZ"

FULL = {
    "supportCode": CODE, "runCount": 1, "runsOnDisk": 12, "sessionCount": 10,
    "machineIncluded": True, "sizeBytes": 383058, "uncompressedBytes": 1204882,
    "maxRunsApplied": 30, "selectionApplied": True, "requesterScoped": True,
    "runsRequested": 1, "runsNotOnDisk": 0, "runsNotAttributed": 0,
    "runsOverCap": 0, "droppedForSize": [], "sourcesRefused": [],
}


def line(**over) -> str:
    return research._send_logs_summary_line({**FULL, **over})


# ══ 1. the facts that are always there ═════════════════════════════════
def test_the_clean_line_names_every_fact_that_always_means_something():
    """⭐ THE REAL FIELD BUNDLE, K1PJJZG8: 1 run, 10 sessions, machine included,
    383,058 bytes, nothing dropped, nothing refused, nothing unattributed. This
    is the line that run would have produced."""
    out = line()
    assert out.startswith(f"[send-logs] built {CODE}: ")
    for fact in ("1 run of 12 on disk", "10 session(s)", "machine=yes",
                 "383058 bytes (1204882 raw)", "cap 30"):
        assert fact in out, f"missing: {fact}\n{out}"


def test_the_support_code_is_in_it_because_that_is_the_rendezvous_key():
    """⛔ A summary that cannot be tied back to the code the person quotes is a
    summary nobody can use. Two sends a minute apart are otherwise identical."""
    assert CODE in line()
    assert "built ?:" in research._send_logs_summary_line({})


def test_singular_and_plural_because_1_runs_reads_as_a_bug():
    assert "1 run of" in line(runCount=1)
    assert "3 runs of" in line(runCount=3)
    assert "0 runs of" in line(runCount=0)


def test_the_machine_flag_is_a_word_not_a_bool():
    # ⛔ `machine=True` is a Python repr leaking into a support artefact.
    assert "machine=yes" in line(machineIncluded=True)
    assert "machine=no" in line(machineIncluded=False)
    assert "True" not in line(machineIncluded=True)


def test_runs_on_disk_is_reported_beside_runs_sent():
    """⭐ THE PAIR IS THE POINT. "1 run" alone cannot distinguish "they picked one
    of twelve" from "the machine only had one" — and those lead to opposite
    conclusions about whether the logs somebody is asking for still exist."""
    out = line(runCount=1, runsOnDisk=12)
    assert "1 run of 12 on disk" in out


def test_both_byte_counts_because_one_of_them_explains_the_other():
    """A 383 KB archive holding 1.2 MB of text is the compression working. The
    same 383 KB holding 400 KB means the tails were nearly all binary or the
    trim ate most of it — and only the pair separates those."""
    out = line(sizeBytes=383058, uncompressedBytes=1204882)
    assert "383058" in out and "1204882" in out


# ══ 2. the counts that appear only when they mean something ════════════
def test_a_clean_run_does_NOT_end_in_a_row_of_zeroes():
    """⛔⛔ THE LOG-NOISE RULE, applied on the way in. A line that always ends
    `0 not on disk, 0 not attributed, 0 over cap` trains people to stop reading
    it, and this line exists to be read."""
    out = line()
    for noise in ("not on disk", "not attributed", "over cap",
                  "dropped for size", "refused"):
        assert noise not in out, f"zero-noise leaked: {noise}\n{out}"


@pytest.mark.parametrize("key,word", [
    ("runsNotOnDisk", "not on disk"),
    ("runsNotAttributed", "not attributed"),
    ("runsOverCap", "over cap"),
])
def test_but_a_NON_zero_one_is_always_said(key, word):
    """⛔⛔ `runsNotAttributed` is the sharpest of the three: it means the picker
    offered a run and the machine then refused to hand it over, so the person
    ticked something and did not send it. Silence there is the one outcome that
    makes the whole per-run feature look broken with no evidence why."""
    assert word in line(**{key: 2})
    assert f"2 {word}" in line(**{key: 2})


def test_the_dropped_and_refused_lists_are_NAMED_not_counted():
    """⛔ A count cannot be chased. "1 older item left out" leaves a support
    engineer unable to tell the reporter WHICH run is missing from the archive
    they are looking at."""
    out = line(droppedForSize=["chat_1_1_20260801T000000"], sourcesRefused=["odd.bin"])
    assert "dropped for size: chat_1_1_20260801T000000" in out
    assert "refused: odd.bin" in out


def test_asked_for_reads_against_the_leading_count():
    """⛔ "asked for 6" beside a leading "3 runs", not "picked 6" — a reader
    should not have to connect two numbers to notice three are missing."""
    out = line(runCount=3, runsRequested=6)
    assert "3 runs of" in out and "asked for 6" in out
    # and when they all arrived it says so rather than repeating the number
    assert "picked, all present" in line(runCount=1, runsRequested=1)


# ══ 3. whether a selection happened at all ═════════════════════════════
def test_it_says_when_NO_selection_was_applied():
    """⛔⛔ THE ONE BOOLEAN A DROPPED KWARG SILENTLY FLIPS. Every test stub for
    the builder in this repo is `lambda dest, **k`, so a lost `only_runs=` is
    invisible to all of them — the request names two runs and the newest thirty
    ship. This is the line that would say so."""
    out = line(selectionApplied=False)
    assert "no selection — newest N" in out
    assert "picked" not in out and "asked for" not in out


def test_and_whether_it_was_scoped_to_the_submitter():
    """A sharer's bundle is scoped; an owner's whole-machine send is not. The two
    have different contents, and the row is not the artefact being read."""
    assert "scoped to the submitter" in line(requesterScoped=True)
    assert "scoped to the submitter" not in line(requesterScoped=False)


# ══ 4. it survives a summary that is missing things ════════════════════
def test_a_partial_summary_still_produces_a_line():
    """⛔ It runs inside the `except` reach of the build worker. A formatter that
    raised on a missing key would turn a successful send into a logged failure —
    the one thing a diagnostic line must never do."""
    assert research._send_logs_summary_line({}).startswith("[send-logs] built ?:")
    assert research._send_logs_summary_line({"runCount": None, "sizeBytes": None})
    assert "0 bytes" in research._send_logs_summary_line({"sizeBytes": None})


def test_it_reads_the_SUMMARY_and_never_the_request():
    """⛔⛔ THE PROVENANCE RULE, same as `maxRunsApplied` and `selectionApplied`.
    A line assembled from the caller's own variables would report the bound that
    was ASKED for — which is exactly the discrepancy somebody reads this line to
    find. So it takes ONE argument, and that argument is the builder's report:
    there is no second input it could disagree with."""
    import inspect
    sig = inspect.signature(research._send_logs_summary_line)
    assert list(sig.parameters) == ["summary"]


def test_and_it_reads_the_BUILDER_S_cap_not_the_caller_S():
    """⛔ The builder reports `maxRunsApplied` precisely so a dropped `max_runs=`
    cannot leave a 30 on the record while three runs shipped against a request
    for three. The line has to quote the builder's number for that to be worth
    anything."""
    assert "cap 7" in line(maxRunsApplied=7)
    assert "cap 30" not in line(maxRunsApplied=7)


# ══ 5. the CALLER, because a formatter nobody calls logs nothing ═══════
class _FakeDoc:
    def __init__(self, sink, path):
        self.sink, self.path = sink, path

    def collection(self, name):
        return _FakeCol(self.sink, f"{self.path}/{name}")

    def get(self):
        outer = self

        class _Snap:
            def to_dict(self):
                return outer.sink.get(outer.path)
        return _Snap()

    def set(self, payload, **_kw):
        self.sink[self.path] = {**(self.sink.get(self.path) or {}), **payload}
        self.sink["_ops"].append(("set", self.path, payload))

    def update(self, payload):
        self.sink[self.path] = {**(self.sink.get(self.path) or {}), **payload}
        self.sink["_ops"].append(("update", self.path, payload))


class _FakeCol:
    def __init__(self, sink, path):
        self.sink, self.path = sink, path

    def document(self, name):
        return _FakeDoc(self.sink, f"{self.path}/{name}")


class _FakeDb:
    def __init__(self, sink):
        self.sink = sink

    def collection(self, name):
        return _FakeCol(self.sink, name)


@pytest.fixture()
def wired(monkeypatch):
    """The send-logs worker, with the build and the upload faked and every log
    line captured in order. ⭐ ORDER IS THE POINT — see the test below."""
    sink = {"_ops": []}
    sink["devices/d-1"] = {"ownerUid": "user-rocky", "sharedWith": []}
    monkeypatch.setattr(research, "_firebase_db", _FakeDb(sink))
    monkeypatch.setattr(research, "_be_payload", lambda d: {**d, "deviceId": "d-1"})
    monkeypatch.setattr(research, "_grpc_write_with_heal", lambda op, what=None, **k: op())
    monkeypatch.setattr(research, "WORKER_ID", 1)
    monkeypatch.setattr(research, "_send_logs_cooldown_remaining", lambda *a, **k: 0)
    monkeypatch.setattr(research, "_stamp_send_logs_attempt", lambda *a, **k: None)

    # ⛔⛔ THE LEVEL IS CAPTURED, NOT DISCARDED. The first version of this fixture
    # threw it away, and a mutant that filed the summary at WARN survived — a
    # successful send reading as a problem in a log people scan by severity. This
    # project has already misread its own log severity as system health once and
    # reported three non-problems as defects, so severity is a fact under test.
    said: "list[tuple[str, str]]" = []
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO": said.append((level, str(msg))))
    monkeypatch.setattr(research, "_build_log_bundle",
                        lambda dest, **k: {**FULL, "path": dest,
                                           "machineIncluded": bool(k.get("include_machine"))})

    def _upload(*_a, **_k):
        said.append(("INFO", "<<UPLOAD>>"))
        return "logs/x/y/z/bundle.zip"
    monkeypatch.setattr(research, "_upload_log_bundle_via_storage_rest", _upload)

    class _Inline:
        def __init__(self, target=None, **kw):
            self._target = target

        def start(self):
            self._target()
    monkeypatch.setattr(research._log_threading, "Thread", _Inline)

    research._send_logs_inflight = False
    return said


def _send(data, selected=True):
    research._handle_send_logs_command(data, "d-1", selected=selected)


def _cmd(**over):
    base = {"action": research.SEND_LOGS_SELECTED_ACTION, "code": CODE,
            "requestId": "req-1", "submittedBy": "user-rocky", "consent": True,
            "runNames": ["chat_1_1_20260824T000000"]}
    base.update(over)
    return base


def test_the_worker_ACTUALLY_logs_the_summary(wired):
    """⭐⭐ THE STANDING LESSON: extracting a formatter does not write a log line.
    A perfect one the worker never calls leaves the log exactly as it was found —
    `received` and `bundle uploaded (N bytes)` — which is the whole defect."""
    _send(_cmd())
    assert any("[send-logs] built" in m for _lvl, m in wired), wired


def test_it_is_logged_BEFORE_the_upload(wired):
    """⛔⛔ ORDER IS LOAD-BEARING. The local copy is kept on purpose — it is the
    floor the whole design rests on, and `--doctor` prints where it is — so a
    build that succeeds and an upload that fails still has to leave a record of
    what the file on disk contains. Logging after the upload would lose exactly
    the case where the log is the only evidence left."""
    _send(_cmd())
    built = next(i for i, (_l, m) in enumerate(wired) if "[send-logs] built" in m)
    uploaded = next(i for i, (_l, m) in enumerate(wired) if m == "<<UPLOAD>>")
    assert built < uploaded, wired


def test_it_is_an_INFO_line_and_not_a_warning(wired):
    """⛔ A SUCCESSFUL SEND IS NOT A PROBLEM. Filing this at WARN would make every
    completed bundle read as one in a log people scan by severity — and the
    failure line beside it already owns ERROR, so the two would stop being
    distinguishable at a glance."""
    _send(_cmd())
    levels = {lvl for lvl, m in wired if "[send-logs] built" in m}
    assert levels == {"INFO"}, wired


def test_the_line_agrees_with_what_the_row_was_given(wired):
    """⛔ TWO REPORTS OF ONE BUILD. The row and the log are written from the same
    summary a few lines apart, and a reader comparing them is the reason both
    exist — so a disagreement between them is worse than either being absent."""
    _send(_cmd())
    said = next(m for _lvl, m in wired if "[send-logs] built" in m)
    assert "1 run of 12 on disk" in said
    assert "10 session(s)" in said
    assert "machine=no" in said, "the box was not ticked, so the line must say so"


def test_and_it_follows_the_TICK_BOX_like_the_row_does(wired):
    """The machine-level material is opt-in as of 2026-08-25. A line that always
    said `machine=yes` would misreport the majority of sends."""
    _send(_cmd(includeMachine=True))
    assert any("machine=yes" in m for _lvl, m in wired), wired


def test_a_build_that_THROWS_still_logs_its_failure_and_not_a_summary(wired,
                                                                     monkeypatch):
    """⛔ The summary line sits inside the worker's `try`. If the build raises
    there is no summary to print, and the existing failure line is what has to
    survive — a formatter that ran on a half-built dict would bury it."""
    def _boom(dest, **k):
        raise OSError("disk went away")
    monkeypatch.setattr(research, "_build_log_bundle", _boom)
    _send(_cmd())
    assert any("bundle failed: OSError" in m for _lvl, m in wired), wired
    assert not any("[send-logs] built" in m for _lvl, m in wired), wired
