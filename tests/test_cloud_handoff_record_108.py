"""The run's record has to survive the hand-off, and stay in its own folder.

⛔⛔ THREE FILED ITEMS, ONE MECHANISM — proved on a real disk before a line was
written. `log()` copies each line into `_RUN_LOG_SINKS[-1]`, a module-global
stack read at WRITE time. The P4/P5 drive posts with a 3600-second timeout and
writes its outcome minutes later, by which point this run's sink has been
popped. So:

  · "Nothing on the server records that a run reached the last two phases" —
    the machine's own account of the hand-off lands in no run folder;
  · "One person's run outcome can land in another person's support bundle" —
    if the NEXT run has armed a sink by then, it lands in THAT folder;
  · task #524, "the machine records the runs the web refuses" — on a 401/403
    the web deliberately writes nothing (no verified identity to write under)
    and says in its own words that this half belongs to the machine, which
    "already sees the non-200 and records nothing".

MEASURED, not argued: across the three run folders on this machine the drive's
own outcome strings appear ZERO times, while the synchronous marker line
written one second earlier — same run, same function, worker thread — is there,
and that folder's last line is `Browser closed`, one second after it.

⭐ THE FIX IS A THIRD USE OF A SHAPE THIS FILE ALREADY HAS TWICE:
`_patch_run_log_status` reaches into a finalized `meta.json`, `_pull_cloud_logs`
drops `cloud.log` into a sealed folder. The collector walks `folder.rglob("*")`,
so a new file rides the support bundle with no collector change at all.
"""
import json

import pytest

import research


@pytest.fixture
def runs(tmp_path, monkeypatch):
    root = tmp_path / "logs" / "runs"
    root.mkdir(parents=True)
    monkeypatch.setattr(research, "_runs_log_root", lambda: root)
    return root


def _folder(runs, name, research_id, *, mtime=None):
    d = runs / name
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({
        "schema": 1, "researchId": research_id, "status": "complete",
    }), encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(d, (mtime, mtime))
    return d


def _handoff(d):
    p = d / research.CLOUD_HANDOFF_FILENAME
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ══ 1. the line lands in the run it is about ═══════════════════════════
def test_the_handoff_line_goes_into_that_research_s_own_folder(runs):
    mine = _folder(runs, "Topic_A_20260101T000000", "chat_A")
    assert research._note_cloud_handoff("chat_A", "P4/P5 dispatched ✓") is True
    assert "P4/P5 dispatched ✓" in _handoff(mine)


def test_it_does_NOT_go_into_whichever_run_happens_to_be_armed(runs, monkeypatch):
    """⛔⛔ THE CROSS-RUN MIS-ATTRIBUTION, WHICH IS THE WHOLE POINT. The old
    path resolved the destination from a module-global stack at write time, so
    a slow encode finishing after the next run started put run A's line in run
    B's folder — and B's support bundle."""
    a = _folder(runs, "Topic_A_20260101T000000", "chat_A")
    b = _folder(runs, "Topic_B_20260101T010000", "chat_B")

    # The state that used to decide it: B's sink armed, A's long gone.
    class _Sink:
        dir = b
        research_id = "chat_B"

    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [_Sink()])
    research._note_cloud_handoff("chat_A", "P4/P5 refused by the cloud — HTTP 403")

    assert "403" in _handoff(a), "the line did not reach the run it is about"
    assert _handoff(b) == "", (
        "run A's hand-off landed in run B's folder — and would ship in B's bundle")


def test_a_research_with_no_folder_is_a_quiet_false_not_a_raise(runs):
    """⭐ This runs on a detached daemon thread inside a `try` whose failure
    mode is losing the rest of the hand-off. Clear Logs, the 7-day sweep and a
    machine that never captured the run all reach here."""
    assert research._note_cloud_handoff("chat_missing", "anything") is False
    assert research._note_cloud_handoff("", "anything") is False
    assert research._note_cloud_handoff("chat_A", "") is False


def test_a_folder_removed_between_listing_and_writing_is_not_recreated(runs, monkeypatch):
    """⛔ RE-CHECKED IMMEDIATELY BEFORE THE WRITE. Re-creating it would leave a
    directory holding one line and no meta for the next sweep to puzzle over —
    the same care `_pull_cloud_logs` takes for the same reason."""
    d = _folder(runs, "Topic_A_20260101T000000", "chat_A")
    real = research._run_folders_for_research_any

    def _vanishing(rid, root=None):
        found = real(rid, root)
        import shutil
        shutil.rmtree(d)
        return found

    monkeypatch.setattr(research, "_run_folders_for_research_any", _vanishing)
    assert research._note_cloud_handoff("chat_A", "late line") is False
    assert not d.exists(), "the folder was re-created behind a sweep's back"


def test_lines_accumulate_rather_than_replacing_each_other(runs):
    """A run can dispatch, be refused, and be retried. Each attempt is a fact."""
    d = _folder(runs, "Topic_A_20260101T000000", "chat_A")
    research._note_cloud_handoff("chat_A", "first")
    research._note_cloud_handoff("chat_A", "second")
    body = _handoff(d)
    assert "first" in body and "second" in body
    assert body.count("\n") == 2


def test_it_writes_its_own_file_and_never_reopens_the_sealed_run_log(runs):
    """⛔ `finalize()` CLOSES the capped writer and `write_line` on a closed
    writer is a silent no-op, so a line appended to `run.log` after the seal is
    lost exactly when it matters most. It also must not disturb `meta.json`,
    which the bundle index and the sweeps both read."""
    d = _folder(runs, "Topic_A_20260101T000000", "chat_A")
    (d / "run.log").write_text("=== super research run ===\n", encoding="utf-8")
    before_meta = (d / "meta.json").read_text(encoding="utf-8")
    research._note_cloud_handoff("chat_A", "after the seal")
    assert (d / "run.log").read_text(encoding="utf-8") == "=== super research run ===\n"
    assert (d / "meta.json").read_text(encoding="utf-8") == before_meta
    assert "after the seal" in _handoff(d)


# ══ 2. the resolver, and why it is not the sweep's ═════════════════════
def test_the_resolver_matches_on_meta_not_on_the_folder_name(runs):
    """⛔ The folder name is sanitised, so two researches can share a prefix —
    and a research whose id the pattern strips does not appear in its own name
    at all. The sweep learned this the expensive way; so does this."""
    right = _folder(runs, "Shared_Prefix_20260101T000000", "chat_AAAA")
    _folder(runs, "Shared_Prefix_20260101T010000", "chat_BBBB")
    found = research._run_folders_for_research_any("chat_AAAA")
    assert found == [right]


def test_the_resolver_INCLUDES_a_live_folder_unlike_the_sweep_s(runs, monkeypatch):
    """⛔⛔ THE DIFFERENCE THAT MATTERS, AND THE REASON THIS IS NOT A REUSE.
    `_run_log_folders_for_research` skips any folder a sink is armed on —
    correct for a delete path, wrong here. The drive starts while the pipeline
    is still finishing, so its first line can arrive BEFORE the seal; borrowing
    the sweep's resolver would drop that line and leave the harder case looking
    handled."""
    d = _folder(runs, "Topic_A_20260101T000000", "chat_A")

    class _Sink:
        dir = d
        research_id = "chat_A"

    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [_Sink()])
    assert research._run_folders_for_research_any("chat_A") == [d]
    # the sweep's resolver, for contrast, refuses it — that is its job
    assert research._run_log_folders_for_research("chat_A", root=runs) == []


def test_an_unreadable_meta_is_skipped_rather_than_matched(runs):
    """⭐ A folder with no meta reads back as researchId "" — and "" == "" is a
    match. The sweep's own comment records that one malformed file nearly cost
    it a tree of somebody's diagnostics."""
    (runs / "half_written").mkdir()
    (runs / "half_written" / "meta.json").write_text("{not json", encoding="utf-8")
    good = _folder(runs, "Topic_A_20260101T000000", "chat_A")
    assert research._run_folders_for_research_any("chat_A") == [good]
    assert research._run_folders_for_research_any("") == []


# ══ 3. the caller, because a helper is not a consumer ══════════════════
#: A 200 from a route that RAN the chain. ⛔ The `p5` key is load-bearing, not
#: decoration: a 200 carrying no `p5` is the route saying it answered phase 4
#: and stopped, and the drive asks again for phase 5 alone. `"{}"` would make
#: every "the route ran it" case below a follow-up case instead.
_RAN = '{"p5": {"ok": true}}'
#: The same 200 the already-completed short-circuit and the GCS branch send.
_P4_ONLY = '{"already_completed": true, "youtube_url": "https://y/1"}'


def _drive(**kw):
    """Run the real drive with fake effects. Returns (verdict, record).

    ⛔⛔ THE FOUR TESTS THAT STOOD HERE READ `_drive_once`'s PARSE TREE — which
    branch came first, which name appeared inside which handler — and wave 10.9
    turned the single POST into a retry ladder (542-5), so every one of them was
    asking about a shape that no longer exists. They are rebuilt here as
    EXECUTIONS: the ladder, the classification, the sentences and the record all
    run, and a mutant that neuters any of them has to survive a real call."""
    calls = {"posts": [], "notes": [], "failures": [], "slept": [], "p5only": []}
    answers = list(kw.get("answers") or [])

    def _post(_token, _p5_only=False):
        calls["posts"].append(_token)
        calls["p5only"].append(_p5_only)
        a = answers[min(len(calls["posts"]), len(answers)) - 1] if answers else (200, '{"p5":{}}')
        if isinstance(a, BaseException):
            raise a
        return a

    tokens = list(kw.get("tokens") or ["tok"])

    def _mint():
        return tokens[min(len(calls["posts"]), len(tokens) - 1)]

    verdict = research._drive_cloud_phases(
        "uid-1", kw.get("rid") or "rid-abcdef01",
        post=_post,
        mint_token=kw.get("mint_token") or _mint,
        sleep=calls["slept"].append,
        note=calls["notes"].append,
        record_failure=calls["failures"].append,
    )
    return verdict, calls


def test_the_drive_records_every_outcome_it_can_have():
    """⛔⛔ HELPER-PINNED, CONSUMER-NOT is this project's commonest miss. Every
    outcome the drive can reach leaves a line in the run's own folder — the
    refusal above all, because it is the one the web deliberately does not
    write (task #524)."""
    for answers, expected in (
        ([(200, _RAN)], "ran"),
        ([(202, '{"in_flight":true}')], "claimed"),
        ([(400, "invalid json")], "refused"),
    ):
        verdict, calls = _drive(answers=answers)
        assert verdict == expected, (expected, verdict)
        assert calls["notes"], f"the {expected} outcome left no record"
    # and the transport failures, both directions
    import requests as rq
    verdict, calls = _drive(answers=[rq.exceptions.ConnectTimeout("no route")])
    assert verdict == "retry"
    assert calls["notes"], "a dispatch that never reached the cloud leaves no record"


def test_only_a_refusal_and_an_exhausted_ladder_are_written_to_the_run():
    """⛔⛔ THE RECORD ON THE DOCUMENT IS NOT THE RECORD IN THE FOLDER. A 200, a
    202 and a mid-flight cut all mean somebody is running the chain — writing
    phase 4 "errored" over any of them would paint a red tile on a healthy run.
    Only an outright refusal, or a ladder that ran out with nothing landed, is
    the machine's to report."""
    import requests as rq
    for answers in ([(200, _RAN)], [(202, "{}")],
                    [rq.exceptions.ReadTimeout("cut at 300s")]):
        _verdict, calls = _drive(answers=answers)
        assert calls["failures"] == [], f"{answers} was written to the run as a failure"
    _verdict, calls = _drive(answers=[(400, "invalid json")])
    assert len(calls["failures"]) == 1, "a refusal left nothing the chat can show"
    assert "refused" in calls["failures"][0]


def test_a_connection_cut_mid_flight_is_not_reported_as_never_arriving():
    """⛔⛔ THE FIRST VERSION OF THIS RECORD LIED ON THE MAJORITY PATH, and the
    wave's own measurement convicted it. Something in front of Cloud Run severs
    this socket at EXACTLY 300 seconds while the route keeps working — one
    measured run finished at 497s — so `requests` raises on every P4/P5 longer
    than five minutes, and the exception branch wrote "never reached the cloud …
    still on phase 3" into the run's permanent record on runs that SUCCEEDED.
    A lying diagnostic is worse than none, and this file rides the support
    bundle.

    ⛔ AND IT IS NOT RETRIED. The cloud has the request; asking again would at
    best take a 202 off the claim the first call already made."""
    import requests as rq
    verdict, calls = _drive(answers=[rq.exceptions.ReadTimeout("severed")])
    assert verdict == "cut"
    assert len(calls["posts"]) == 1, "a request the cloud received was sent twice"
    said = " ".join(calls["notes"])
    assert "may be finishing it" in said
    assert "never reached the cloud" not in said, (
        "a socket cut after the cloud had the request was filed as one that "
        "never left this machine")
    # ⭐ and the genuine never-arrived case keeps its own sentence
    _v, calls = _drive(answers=[rq.exceptions.ConnectTimeout("no route")] * 5)
    assert "never reached the cloud" in " ".join(calls["notes"])


def test_the_classification_is_EXECUTED_not_read():
    """⛔⛔ A MUTANT NEUTERED THIS TO `False and isinstance(...)` AND EVERY
    ASSERTION STAYED GREEN, because they read the parse tree for NAMES and the
    names survive. That is the fifth time in this wave that a pin of mine
    measured nothing, and the fix is the same each time: extract the decision
    and run it."""
    import requests as rq
    ex = rq.exceptions
    # ⭐ THE UNAMBIGUOUS CLASSES ANSWER ON THEIR OWN, and the clock does not
    # overrule them: a black-holed SYN fails at the OS connect timeout, tens of
    # seconds in, far past any threshold.
    for exc in (ex.ConnectTimeout("t"), ex.ProxyError("p")):
        assert research._dispatch_never_left(exc, 120) is True, type(exc).__name__
        assert research._dispatch_never_left(exc, 3600) is True, type(exc).__name__
    # ⛔⛔ AND A BARE ConnectionError IS NOT ONE OF THEM — round three of
    # cross-verify induced the real exception and this assertion used to say the
    # opposite. urllib3 wraps a socket cut MID-FLIGHT in the same class it uses
    # for a connection that never opened:
    #   ConnectionError(ProtocolError('Connection aborted.', ConnectionResetError))
    # and that is this route's DEFINING failure — something in front of Cloud
    # Run severs it at exactly 300 s while the request keeps being served, one
    # measured run finishing at 497 s. Answering "never left" for those wrote a
    # false sentence into the permanent record of runs that SUCCEEDED, which is
    # the exact defect round one removed. So the clock keeps this one.
    assert research._dispatch_never_left(ex.ConnectionError("c"), 3600) is False
    assert research._dispatch_never_left(ex.ConnectionError("c"), 300) is False
    assert research._dispatch_never_left(ex.ConnectionError("c"), 1) is True
    # ⭐ AND THE REAL ONE, BUILT THE WAY urllib3 BUILDS IT — a bare
    # `ConnectionError("c")` is my own construction and could be the only shape
    # this rule handles correctly.
    import urllib3.exceptions as _u3
    _real = ex.ConnectionError(_u3.ProtocolError(
        "Connection aborted.", ConnectionResetError(54, "Connection reset by peer")))
    assert research._dispatch_never_left(_real, 300) is False
    assert research._dispatch_never_left(_real, 497) is False
    # received — the cloud had it and this machine stopped watching
    for exc in (ex.ReadTimeout("r"), ex.ChunkedEncodingError("c")):
        assert research._dispatch_never_left(exc, 301) is False, type(exc).__name__
    # ⛔ AND BOTH OF THOSE ANSWER BEFORE THE CLOCK COULD AGREE WITH THEM. Tested
    # only at 301 s, the `elapsed < 10` fallback returns False anyway, so
    # deleting either class from the tuple left the suite green — round three
    # executed both values to find it. A body-stream break moments after
    # dispatch is still a request the cloud received.
    assert research._dispatch_never_left(ex.ReadTimeout("r"), 1) is False
    assert research._dispatch_never_left(ex.ChunkedEncodingError("c"), 1) is False
    # ⭐ AND THE ORDER OF THE CHECKS IS LOAD-BEARING, EXECUTED RATHER THAN
    # CLAIMED. The old comment asserted this was true "in some versions" and
    # pinned nothing; in the pinned requests it is false, so the claim was
    # unfalsifiable. A class that IS both must read as received.
    class _Both(ex.ReadTimeout, ex.ConnectionError):
        pass
    assert research._dispatch_never_left(_Both("b"), 3600) is False
    # an exception class we cannot place falls back to the clock
    assert research._dispatch_never_left(ValueError("?"), 1) is True
    assert research._dispatch_never_left(ValueError("?"), 3600) is False


def test_the_exception_CLASS_decides_whether_the_request_ever_left():
    """⛔⛔ THE CLOCK NAMES THE WRONG SUBJECT ON ITS OWN, which round two of
    cross-verify proved. A black-holed SYN does not fail instantly — it fails at
    the OS connect timeout, tens of seconds later, past any elapsed-time
    threshold — so a time-only rule filed a request that never left the machine
    as one the cloud received, in the run's permanent support-bundle record.
    `requests` names that case exactly: ConnectTimeout, and ProxyError.

    ⛔⛔ AND ROUND THREE CORRECTED THE CORRECTION. A bare `ConnectionError` does
    NOT name it — urllib3 raises the same class for a socket cut mid-flight, so
    routing every one of them to "never left" re-broke the majority path.

    ⭐ EXECUTED THROUGH THE VERDICT, not read off the drive's parse tree: the
    classifier has to be what decides, and the only proof of that is two
    exception classes taking two different branches through the real function."""
    import requests as rq
    ex = rq.exceptions
    # never left → retried
    assert research._dispatch_verdict(exc=ex.ConnectTimeout("t"), elapsed_sec=120) == "retry"
    assert research._dispatch_verdict(exc=ex.ProxyError("p"), elapsed_sec=3600) == "retry"
    # received → not retried
    assert research._dispatch_verdict(exc=ex.ReadTimeout("r"), elapsed_sec=1) == "cut"
    _real = ex.ConnectionError(__import__("urllib3").exceptions.ProtocolError(
        "Connection aborted.", ConnectionResetError(54, "Connection reset by peer")))
    assert research._dispatch_verdict(exc=_real, elapsed_sec=300) == "cut"
    # and the drive acts on the difference: one is asked again, the other is not
    _v, never = _drive(answers=[ex.ConnectTimeout("no route"), (200, _RAN)])
    assert len(never["posts"]) == 2, "a request that never left was not retried"
    _v, cut = _drive(answers=[ex.ReadTimeout("severed"), (200, _RAN)])
    assert len(cut["posts"]) == 1, "a request the cloud received was sent again"


def test_the_ladder_retries_what_can_clear_and_refuses_what_cannot():
    """⛔⛔ THE WHOLE OF 542-5. A single POST meant no token, a POST that never
    left, or one 5xx delivered nothing at all: no video, no Super Research, no
    Doc, no email, and a run reading "ongoing" until somebody opened its chat.

    ⛔ 401 AND 403 ARE THE ONLY 4xx RETRIED, and they are retried with a FRESH
    token — a stale ID token and a claim-propagation race are exactly what they
    look like. A 400 cannot clear, and repeating it only adds load."""
    # a 5xx clears on the second ask
    verdict, calls = _drive(answers=[(503, "try again"), (200, _RAN)])
    assert verdict == "ran" and len(calls["posts"]) == 2
    assert calls["slept"], "the retry did not back off"
    # a 401 is retried, with a token minted again for the second attempt
    verdict, calls = _drive(answers=[(401, "unauthorized"), (200, _RAN)],
                            tokens=["stale", "fresh"])
    assert verdict == "ran"
    assert calls["posts"] == ["stale", "fresh"], (
        "the retry re-used the token the route had just rejected")
    # a 403 likewise
    verdict, calls = _drive(answers=[(403, "device not authorized"), (200, _RAN)])
    assert verdict == "ran" and len(calls["posts"]) == 2
    # ⛔ and a refusal stops at once
    verdict, calls = _drive(answers=[(400, "invalid json"), (200, _RAN)])
    assert verdict == "refused"
    assert len(calls["posts"]) == 1, "a refusal on the merits was asked again"
    assert calls["slept"] == []


def test_a_route_that_answered_phase_4_and_stopped_is_asked_for_phase_5():
    """⛔⛔ THE ROUTE SAYS SO IN ITS OWN WORDS AND THE MACHINE WAS NOT LISTENING
    (wave 10.9, 542-5). `casRouteP4`'s already-completed short-circuit answers
    200 with the video link and NO `p5` key, and its comment names the contract:
    "the browser reads exactly that as 'ask for phase 5 alone'". The GCS-link
    branch answers the same way.

    That is precisely the shape a RE-KICK lands on — the boot rehydrate and the
    Resume both fire at runs whose phase 4 may already be done — so the machine
    took a 200, called the chain finished, and left phase 5 unrun: no Super
    Research, no Doc, no email, with nobody awake to notice. #542's symptom,
    reached through the fix for it."""
    verdict, calls = _drive(answers=[(200, _P4_ONLY), (200, _RAN)])
    assert verdict == "ran"
    assert calls["p5only"] == [False, True], (
        "the route answered phase 4 without phase 5 and the machine stopped")
    said = " ".join(calls["notes"])
    assert "asking it for phase 5 alone" in said
    assert calls["failures"] == []


def test_the_follow_up_is_asked_once_and_gets_its_own_budget():
    """⛔ ONCE: the `p5_only` answer always carries `p5`, but a route that
    somehow answered without it must not put the drive in a loop.

    ⭐ AND ITS OWN BUDGET, because phase 5 is the rest of the run, not a
    postscript to the attempts phase 4 happened to use up."""
    # the follow-up itself answers without p5 — it is not asked a third time
    verdict, calls = _drive(answers=[(200, _P4_ONLY), (200, _P4_ONLY)])
    assert verdict == "ran"
    assert calls["p5only"] == [False, True]
    # phase 4 burns most of the ladder; phase 5 still gets a full one
    verdict, calls = _drive(answers=[(503, "x"), (503, "x"), (503, "x"), (503, "x"),
                                     (200, _P4_ONLY), (503, "x"), (200, _RAN)])
    assert verdict == "ran"
    assert calls["p5only"] == [False] * 5 + [True, True]


def test_the_real_post_asks_for_phase_5_alone_when_told_to(monkeypatch):
    """⛔⛔ HELPER-PINNED, CONSUMER-NOT — the harness caught this one too. Every
    test above hands the drive its OWN `post`, so the body the REAL closure
    builds was never executed: dropping `p5_only` from it left them all green
    while the follow-up asked the route to run phase 4 again, got the same
    answer, and delivered nothing.

    ⭐ It is also where the timeout PAIR is executed rather than read. A scalar
    there sets the connect timeout to 3600 too, and a black-holed SYN then fails
    long after the classifier can tell it from a severance."""
    import threading
    import requests
    sent = []
    done = threading.Event()

    class _Resp:
        status_code = 200
        text = _RAN

    monkeypatch.setattr(requests, "post",
                        lambda url, **kw: (sent.append((url, kw)) or _Resp()))

    def _spy(uid, rid, *, post, mint_token, sleep, note, record_failure):
        post("tok", False)
        post("tok", True)
        done.set()
        return "ran"

    monkeypatch.setattr(research, "_drive_cloud_phases", _spy)
    monkeypatch.setattr(research, "_fire_fe_p4_trigger", lambda u, r: True)
    monkeypatch.setattr(research, "_fe_handoff_begin", lambda drive=False: None)
    monkeypatch.setattr(research, "_fe_handoff_end", lambda drive=False: None)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)

    research._post_fe_p4p5_trigger("uid-1", "rid-abcdef01")
    assert done.wait(5), "the dispatch thread never ran"
    assert len(sent) == 2, sent
    first, follow = sent[0][1]["json"], sent[1][1]["json"]
    assert first["research_id"] == "rid-abcdef01" and first["ownerUid"] == "uid-1"
    assert "p5_only" not in first, (
        "the first ask carried p5_only — phase 4 would never run")
    assert follow["p5_only"] is True, (
        "the follow-up asked for the whole chain again, so the route repeats "
        "the phase-4 path and answers the same way")
    assert follow["research_id"] == "rid-abcdef01" and follow["ownerUid"] == "uid-1"
    assert sent[0][1]["timeout"] == (10, 3600)
    assert sent[0][0].endswith("/api/uploadYouTube")


def test_an_unreadable_answer_is_not_a_missing_phase_5():
    """⛔ GUESSING HERE ASKS FOR A PHASE 5 THAT MAY BE MID-FLIGHT. The browser
    reads an unparseable answer as a transport failure and does not follow up;
    this is the same rule. The route streams keep-alive spaces before its JSON,
    so an answer of spaces alone parses to nothing."""
    for body in ("", "   ", "not json at all", "[1,2,3]", '"a string"'):
        assert research._answered_without_phase_5(body) is False, body
    # ⭐ ACCEPT POLARITY, including the leading keep-alive spaces
    assert research._answered_without_phase_5('   {"already_completed": true}') is True
    assert research._answered_without_phase_5('   {"p5": null}') is False


def test_a_missing_token_is_retried_rather_than_returning_in_silence():
    """⛔⛔ `_fresh_user_mode_id_token()` RETURNING None USED TO END THE WHOLE
    HAND-OFF: one INFO line, the marker, and nothing else ever. A refresh that
    blips — DNS, a five-second outage — cost the run its last two phases."""
    minted = []

    def _mint():
        minted.append(1)
        return None if len(minted) < 3 else "tok"

    verdict, calls = _drive(answers=[(200, _RAN)], mint_token=_mint)
    assert verdict == "ran"
    assert len(minted) == 3, "the token was minted once and given up on"
    assert len(calls["posts"]) == 1

    # ⛔ and when it never comes back, the run is told
    verdict, calls = _drive(answers=[(200, _RAN)], mint_token=lambda: None)
    assert verdict == "retry"
    assert calls["posts"] == []
    assert len(calls["failures"]) == 1
    assert "never reached the cloud" in calls["failures"][0]


def test_the_ladder_is_bounded_and_actually_backs_off():
    """⛔ A retry with no ceiling is a thread that never ends and a respawn that
    never happens — `_fe_handoff_begin(drive=True)` holds the process open for
    as long as this runs.

    ⛔⛔ AND THE DELAYS ARE MEASURED AGAINST NUMBERS, NOT AGAINST THE CONSTANT.
    The first version of this asserted `slept == list(_DRIVE_BACKOFF_SEC)`,
    which is a tautology: a mutant that zeroed every delay changed both sides
    and survived. Five requests fired back to back at a route that is
    restarting is not a retry ladder."""
    import requests as rq
    verdict, calls = _drive(answers=[rq.exceptions.ConnectTimeout("no route")] * 20)
    assert verdict == "retry"
    assert len(calls["posts"]) == len(research._DRIVE_BACKOFF_SEC) + 1
    assert len(calls["slept"]) == len(research._DRIVE_BACKOFF_SEC)
    assert all(d >= 1 for d in calls["slept"]), (
        f"the ladder does not pause between attempts: {calls['slept']}")
    assert calls["slept"] == sorted(calls["slept"]), "the backoff does not back off"
    assert 30 <= sum(calls["slept"]) < 600, (
        "the ladder is either too short to outlast a route restart or longer "
        "than anything worth waiting for")


def test_the_connect_phase_is_bounded_below_the_threshold():
    """⛔ `timeout=3600` AS A SCALAR SETS THE CONNECT TIMEOUT TOO. That is what
    let a no-route failure outlive the threshold. A pair bounds the connect
    while leaving the read matched to the route's Cloud Run ceiling."""
    import inspect
    src = inspect.getsource(research._post_fe_p4p5_trigger)
    assert "timeout=(10, 3600)" in src, (
        "the connect phase is unbounded again, so a black-holed SYN fails long "
        "after the discriminator has stopped being able to tell")
    assert "timeout=3600," not in src


def test_the_threshold_is_far_below_the_measured_severance():
    """⭐ 300 seconds is where the real severance lands. The threshold only has
    to separate "never left" (DNS, refused, no route — instant) from anything
    the cloud actually received, so it sits close to zero and nowhere near 300."""
    assert 1 <= research._DRIVE_SENT_AFTER_SEC <= 60


def test_the_real_dispatch_wires_the_record_and_the_refusal(monkeypatch):
    """⛔⛔ HELPER-PINNED, CONSUMER-NOT — and the harness caught it. Every test
    above runs `_drive_cloud_phases` with its OWN `note` and `record_failure`,
    so cutting either wire inside `_post_fe_p4p5_trigger` left all of them
    green: the drive would record its refusals into a lambda that returns None,
    which is #542's symptom exactly.

    This runs the real dispatch and checks what the drive is actually handed."""
    import threading
    seen = {}
    done = threading.Event()

    def _spy(uid, rid, *, post, mint_token, sleep, note, record_failure):
        seen["ids"] = (uid, rid)
        note("a line for the run's own folder")
        record_failure("because the cloud said no")
        done.set()
        return "refused"

    recorded, noted = [], []
    monkeypatch.setattr(research, "_drive_cloud_phases", _spy)
    monkeypatch.setattr(research, "_fire_fe_p4_trigger", lambda u, r: True)
    monkeypatch.setattr(research, "_fe_handoff_begin", lambda drive=False: None)
    monkeypatch.setattr(research, "_fe_handoff_end", lambda drive=False: None)
    monkeypatch.setattr(research, "_record_cloud_kick_refusal",
                        lambda u, r, why: recorded.append((u, r, why)))
    monkeypatch.setattr(research, "_note_cloud_handoff",
                        lambda rid, line: noted.append((rid, line)))
    monkeypatch.setattr(research, "log", lambda *a, **k: None)

    assert research._post_fe_p4p5_trigger("uid-1", "rid-abcdef01") is True
    assert done.wait(5), "the dispatch thread never ran"
    assert seen["ids"] == ("uid-1", "rid-abcdef01")
    assert recorded == [("uid-1", "rid-abcdef01", "because the cloud said no")], (
        "the drive's refusal reached nothing the chat can read")
    # ⛔ AND THE LINE GOES INTO THIS RUN'S OWN FOLDER, addressed by researchId —
    # the whole point of `_note_cloud_handoff` over a bare `log()`.
    assert noted and noted[0][0] == "rid-abcdef01"


def test_the_refusal_line_says_what_happens_next():
    """⭐ A record nobody can act on is a log line with extra steps. The run is
    recoverable — `needsFeTrigger` was written before the POST, and opening the
    chat re-kicks the route — so the sentence says so rather than implying the
    run is lost."""
    _v, calls = _drive(answers=[(400, "invalid json")])
    said = " ".join(calls["notes"])
    assert "opening the chat asks the route again" in said
    assert calls["failures"] and "opening the chat asks the route again" in calls["failures"][0]


def test_the_refusal_line_promises_no_re_drive_that_cannot_happen():
    """⛔⛔ "OPENING THE CHAT ASKS THE ROUTE AGAIN" IS FALSE FOR A RUN THAT KEEPS
    NOTHING (wave 10.9, #536-C11). That re-drive needs somebody to REOPEN the
    research, and an incognito chat is in no list — a closed tab is the end of
    it. This file is the run's permanent account and it rides the support
    bundle, so a lying diagnostic here is the failure this whole seam exists to
    stop, arriving one wave later in a new sentence."""
    _v, calls = _drive(answers=[(400, "invalid json")], rid="incog_1758400000000_1")
    said = " ".join(calls["notes"] + calls["failures"])
    assert "opening the chat asks the route again" not in said, said
    assert "no chat to reopen" in said


def test_a_cut_connection_says_the_same_thing_about_the_same_run():
    """⛔ THE OTHER OUTCOME SENTENCE, and the one a run most often takes: the
    300-second severance. Both must come from the same clause or they drift."""
    _v, ordinary = _drive(answers=[TimeoutError("cut")], rid="chat_1755500000000_1")
    _v2, keeps_nothing = _drive(answers=[TimeoutError("cut")],
                                rid="incog_1758400000000_1")
    assert "opening the chat asks the route again" in " ".join(ordinary["notes"])
    assert "no chat to reopen" in " ".join(keeps_nothing["notes"])


#: What a chain that emails the report can answer with — the mail error names
#: the person's address.
_ADDRESS = "someone@example.com"
_REPLIES = (
    [(500, f"send to {_ADDRESS} failed: 550 mailbox unavailable")],   # retried, gave up
    [(400, f"invalid recipient {_ADDRESS}")],                         # refused
    [(200, f'{{"p5": {{"ok": true, "sentTo": "{_ADDRESS}"}}}}')],    # ran
)


def _everything_the_drive_said(monkeypatch, answers, rid):
    logged = []
    monkeypatch.setattr(research, "log", lambda m, *a, **k: logged.append(str(m)))
    _v, calls = _drive(answers=answers, rid=rid)
    return "\n".join(logged + calls["notes"] + calls["failures"])


@pytest.mark.parametrize("answers", _REPLIES)
def test_a_run_that_keeps_nothing_files_the_status_and_not_the_reply(monkeypatch, answers):
    """⛔⛔ THE REPLY OUTLIVES THE RUN (wave 10.9, last repair). Up to 160
    characters of the route's answer rode `why` into the log, the run's folder
    and the record, after the run had ended — and for a chain that sends the
    report by email, that answer can be the mail error naming the person's
    address. The status says what happened; the text is theirs."""
    said = _everything_the_drive_said(monkeypatch, answers, "incog_1758400000000_1")

    assert _ADDRESS not in said, said
    assert f"HTTP {answers[0][0]}" in said, "the status went too — the line says nothing now"


@pytest.mark.parametrize("answers", _REPLIES)
def test_an_ordinary_run_still_quotes_the_reply(monkeypatch, answers):
    """⭐ ACCEPT POLARITY — the reply is the diagnosis for everybody else."""
    said = _everything_the_drive_said(monkeypatch, answers, "chat_1755500000000_1")

    assert _ADDRESS in said


def test_the_202_is_not_reported_as_a_dispatch():
    """⛔⛔ IT WAS LOGGED "dispatched ✓" (wave 10.9, 542-S4). A 202 means ANOTHER
    caller holds the claim — an open tab, or an earlier kick still running — so
    this call did nothing at all, and the tick said it had. On a run that then
    stalled, the one line the report rested on named the wrong party."""
    verdict, calls = _drive(answers=[(202, '{"in_flight":true}')])
    assert verdict == "claimed"
    said = " ".join(calls["notes"])
    assert "already claimed by another caller" in said
    assert "dispatched" not in said, (
        "a 202 is still being reported as this machine's dispatch")
    # ⭐ ACCEPT POLARITY: a 200 IS this machine's dispatch and still says so.
    _v, ran = _drive(answers=[(200, _RAN)])
    assert "the route ran it" in " ".join(ran["notes"])


# ══ 4. the drive's lines are the machine's (wave 10.10) ════════════════
#
# ⛔⛔ WHAT WAS WRONG. `_note_cloud_handoff` put this run's account into its own
# folder, but the drive's `log()` lines still went into whichever run was armed
# when they were written — minutes after this run's sink was popped. Wave 10.9
# removed the wait that held the next run's start behind this delivery, so on a
# shared computer the next run (somebody else's) now routinely collected this
# run's research id and up to 160 characters of the route's answer in its
# run.log and support bundle. The thread is now a machine line: backend.log
# only. And for a run that keeps nothing, the route's answer stays out of that
# log too — it can be an email error about this very research. (Since wave
# 10.9's last repair, `_quote_reply`, it stays out of the run's own record as
# well: `why` carries the status only, for every line the drive writes.)

INCOG_RID = "incog_1758400000000_7"
SECRET = "could not email the report on a very private subject"


class _NextRunSink:
    """The run armed AFTER this one — somebody else's, on a shared computer."""

    def __init__(self, research_id="chat_NEXT"):
        self.research_id = research_id
        self.lines = []

    def note_line(self, line, level):
        self.lines.append(line)


def _real_drive(monkeypatch, rid, answer):
    """Run the REAL dispatch — its thread, its `_drive`, its ladder — with only
    the network and the disk faked. Returns what `note()` was handed, once the
    thread has finished (its `finally` is the last thing it does)."""
    import threading

    import requests
    finished = threading.Event()
    noted = []

    class _Resp:
        status_code, text = answer

    monkeypatch.setattr(requests, "post", lambda url, **kw: _Resp())
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok")
    monkeypatch.setattr(research, "_fire_fe_p4_trigger", lambda u, r: True)
    monkeypatch.setattr(research, "_fe_handoff_begin", lambda drive=False: None)
    monkeypatch.setattr(research, "_fe_handoff_end",
                        lambda drive=False: finished.set())
    monkeypatch.setattr(research, "_record_cloud_kick_refusal",
                        lambda u, r, why: True)
    monkeypatch.setattr(research, "_note_cloud_handoff",
                        lambda r, line: noted.append((r, line)))
    assert research._post_fe_p4p5_trigger("uid-1", rid) is True
    assert finished.wait(10), "the delivery thread never finished"
    return noted


def test_the_next_runs_folder_gets_none_of_the_drives_lines(monkeypatch, capsys):
    """⛔⛔ THE LEAK. The next person's run is armed while this run's delivery
    finishes; not one of the drive's lines may reach its folder."""
    nxt = _NextRunSink()
    monkeypatch.setattr(research, "_RUN_LOG_SINKS", [nxt])
    noted = _real_drive(monkeypatch, "chat_A0000001", (200, _RAN))
    leaked = [ln for ln in nxt.lines if "FE trigger" in ln or "chat_A00" in ln]
    assert leaked == [], f"run A's delivery landed in the next run's folder: {leaked}"
    # ⭐ ACCEPT POLARITY: the machine's own log still has it, and run A's own
    # account still went to run A.
    assert "the cloud ran the chain" in capsys.readouterr().out
    assert noted and noted[0][0] == "chat_A0000001"


def test_a_private_runs_route_answer_stays_out_of_the_machine_log(monkeypatch, capsys):
    """⛔⛔ Machine lines reach backend.log whatever is armed, so the route's
    answer about a run that keeps nothing must not ride them — driven through
    the real dispatch thread. Its own record gets the status and not the answer
    either (`_quote_reply`, wave 10.9's last repair)."""
    noted = _real_drive(monkeypatch, INCOG_RID,
                        (200, json.dumps({"p5": {"error": SECRET}})))
    out = capsys.readouterr().out
    assert "the cloud ran the chain ✓ (HTTP 200)" in out
    assert SECRET not in out, "a private run's route answer reached backend.log"
    assert noted and all(SECRET not in line for _r, line in noted), noted
    assert any("HTTP 200" in line for _r, line in noted), noted


def test_an_ordinary_runs_route_answer_is_still_logged(monkeypatch, capsys):
    """⭐ ACCEPT POLARITY. An ordinary run's answer has always been in the
    machine's log, and it is the first thing a stuck-run report is read from."""
    _real_drive(monkeypatch, "chat_B0000001",
                (200, json.dumps({"p5": {"error": SECRET}})))
    assert SECRET in capsys.readouterr().out


def test_every_line_the_ladder_logs_for_a_private_run_names_the_status_only(
        monkeypatch):
    """⛔ ALL FOUR LINES THAT CARRY THE ANSWER: the follow-up ask, the retry,
    the give-up after a refusal and after an exhausted ladder. An ordinary
    run's own record keeps the answer each time; a private run's keeps the
    status and not the answer (`_quote_reply`)."""
    for rid, keeps in ((INCOG_RID, False), ("chat_C0000001", True)):
        lines = []
        monkeypatch.setattr(research, "log",
                            lambda msg, level="INFO", _l=lines: _l.append(msg))
        p4_only = json.dumps({"already_completed": True, "detail": SECRET})
        _v, followed = _drive(answers=[(200, p4_only), (200, _RAN)], rid=rid)
        _v, refused = _drive(answers=[(400, SECRET)], rid=rid)
        _v, exhausted = _drive(answers=[(500, SECRET)] * 5, rid=rid)
        said = "\n".join(lines)
        for fragment in ("without running phase 5 (HTTP 200",
                         "(refused: HTTP 400",
                         "did not land (HTTP 500",
                         "(retry: HTTP 500"):
            assert fragment in said, (rid, fragment, said)
        assert (SECRET in said) is keeps, (rid, said)
        for calls in (followed, refused, exhausted):
            assert (SECRET in " ".join(calls["notes"])) is keeps, (
                rid, "the run's own record", calls["notes"])
