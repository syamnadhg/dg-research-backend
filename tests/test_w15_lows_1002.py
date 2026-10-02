"""Wave 15 (10-02) — three lows from the 10-01 and 10-02 logs.

(a) ChatGPT's done check read the hidden old report frame's 13 MB inline
    `<script type=module>` as text (3NH9Q7CH retry1: "DOM not-done:
    stop_btn_present (text=13391747 …)"), and handed that length to the report
    read as what the done check saw. A document that is not drawn answers
    innerText with its whole source; only a drawn document's text counts now.
(b) The Phase 4-5 hand-off logged "the route ran it ✓ (HTTP 200 (<spaces>
    <!doctype html> … <title>Internal Server Error</title> …))": the cloud's front
    door cut the call at 300 s after the keep-alive spaces had sent the status,
    and the cloud finished the run. It is a cut now — the cloud keeps working.
(c) The queued→ongoing flip was refused on every run ("could not open the
    queued→ongoing transaction … stage=BeginTransaction"), 10-02 on a sharer's
    run included, and fell back to a plain read. Ours: the rules deny this
    machine a Firestore transaction on the user tree (#720), so the flip is a
    read plus a compare-and-set update now, which the rules allow.

Each is driven through its real consumer: the done check on a headless page,
the cloud drive with its effects as arguments, the worker's flip lifted out of
`run_server` (`_run_server_closure`).
"""
from __future__ import annotations

import pytest

import research
from _run_server_closure import lift
from test_nlm_customise_0930 import chrome as _customise_chrome  # noqa: F401  (fixture)


@pytest.fixture(scope="module")
def chrome(request):
    """test_nlm_customise_0930's headless Chrome (aliased: see the lint floor)."""
    return request.getfixturevalue("_customise_chrome")


# ══ (a) the done check measures the drawn report only ════════════════════════

#: The finished report, drawn, as the Deep research app's frame shows it.
REPORT = ("<h1>Saint Bernard health</h1>" +
          "<p>Hip dysplasia, bloat and cardiac disease across alpine lines. </p>" * 80)
#: The old report frame, hidden, holding the app's own inline module script.
SCRIPT_BYTES = 2_000_000


def _frames_page(chrome, hidden_too=True):
    pg = chrome.run(chrome.ctx.new_page())
    chrome.run(pg.set_content("<html><body><main><p>chat</p></main></body></html>"))
    chrome.run(pg.evaluate(
        """([report, n, hidden]) => new Promise((done) => {
            const mk = (style, html) => {
                const f = document.createElement('iframe');
                f.style.cssText = style;
                f.srcdoc = html;
                document.body.append(f);
                return new Promise((r) => f.addEventListener('load', r, { once: true }));
            };
            const old = '<html><body><h1>Old report</h1><script type="module">'
                + 'x'.repeat(n) + '</scr' + 'ipt></body></html>';
            Promise.all([
                mk('width:900px;height:700px;border:0',
                   '<html><body><div class="report">' + report + '</div></body></html>'),
                hidden ? mk('display:none', old) : Promise.resolve(),
            ]).then(done);
        })""", [REPORT, SCRIPT_BYTES, hidden_too]))
    return pg


def test_the_done_check_reads_the_drawn_report_not_a_hidden_frames_script(chrome):
    """⭐ The snapshot's text length is the report's, with the hidden old frame's
    script on the page beside it — the same length it reads with no hidden frame
    at all. Before: 2,000,000-odd, the script's source."""
    pg = _frames_page(chrome)
    clean = _frames_page(chrome, hidden_too=False)
    try:
        _done, _reason, snap = chrome.run(research.detect_completion_chatgpt(pg))
        _d2, _r2, snap2 = chrome.run(research.detect_completion_chatgpt(clean))
        drawn = chrome.run(pg.frames[1].evaluate("() => document.body.innerText.length"))
    finally:
        chrome.run(pg.close())
        chrome.run(clean.close())
    assert snap["text_len"] < SCRIPT_BYTES, snap
    assert snap["text_len"] == snap2["text_len"] >= drawn > 4000, (snap, snap2, drawn)


# ══ (b) a 200 that is the front door's error page is a cut ══════════════════

#: What the 10-01 hand-off's answer was: the route's keep-alive spaces, then
#: Google's front-end error page in place of the route's JSON.
CUT_BODY = (" " * 20 + "\n<!doctype html>\n<html>\n  <head>\n    <title>Internal Server "
            "Error</title>\n    <link href='https://fonts.googleapis.com/css?family=Roboto' "
            "rel='stylesheet' type='text/css'>\n  </head>\n  <body>…</body>\n</html>\n")


def _drive(monkeypatch, answers):
    """The REAL cloud drive, its effects recorded. `answers` is what each POST
    returns, in order."""
    notes, failures, posts, lines = [], [], [], []
    seq = list(answers)

    def _post(token, p5_only):
        posts.append(p5_only)
        return seq.pop(0)

    monkeypatch.setattr(research, "log", lambda m, *a, **k: lines.append(str(m)))
    verdict = research._drive_cloud_phases(
        "uid-w15", "chat_1790923944235_2", post=_post, mint_token=lambda: "tok",
        sleep=lambda s: None, note=notes.append, record_failure=failures.append)
    return verdict, notes, failures, posts, lines


def test_a_200_whose_body_is_the_front_doors_error_page_is_a_cut(monkeypatch):
    """⭐⭐ THE 10-01 HAND-OFF. Not "the route ran it ✓": a cut, which says the
    cloud has the request and may be finishing it — and is not retried, which
    could only take a 202 off the route's own claim, nor recorded as a failure.
    The error page is not quoted. Beside it, the route's own JSON after the same
    spaces is still a run."""
    verdict, notes, failures, posts, lines = _drive(monkeypatch, [(200, CUT_BODY)])
    assert verdict == "cut"
    assert posts == [False], "a cut is never asked again"
    assert failures == []
    assert any("connection cut" in n and "The cloud received the request" in n
               for n in notes), notes
    assert not any("ran it ✓" in n for n in notes + lines), notes + lines
    assert not any("<!doctype" in s or "Internal Server Error" in s for s in notes + lines)

    ok, notes2, _f, _p, _l = _drive(monkeypatch, [(200, " " * 20 + '{"p4": {}, "p5": {}}')])
    assert ok == "ran" and any("the route ran it ✓" in n for n in notes2), notes2


@pytest.mark.parametrize("body", ["", " " * 40, "Service Unavailable"],
                         ids=["empty", "only-spaces", "plain-text"])
def test_any_2xx_that_is_not_the_routes_answer_is_a_cut(body):
    """The web reads these the same way ("the route's answer could not be
    read"). A verdict made without a body is unchanged."""
    assert research._dispatch_verdict(status_code=200, body=body) == "cut"
    assert research._dispatch_verdict(status_code=200, body='{"p5": {}}') == "ran"
    assert research._dispatch_verdict(status_code=200) == "ran"


# ══ (c) the flip: a read and a compare-and-set, never a transaction ══════════

class _Gone(Exception):
    pass


class _Snap:
    def __init__(self, data, t):
        self._data, self.update_time = data, t
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data or {})


class _Record:
    """`users/{uid}/researches/{rid}`. `reads` is what each read finds, in order
    (the last one repeats); `refuse_updates` is how many updates fail their
    precondition first."""

    def __init__(self, reads, refuse_updates=0):
        self.reads, self.refuse, self.updates, self.n = list(reads), refuse_updates, [], 0

    def collection(self, _name):
        return self

    document = collection

    def get(self, **kw):
        assert "transaction" not in kw, "the flip read inside a transaction"
        self.n += 1
        found = self.reads[min(self.n, len(self.reads)) - 1]
        if isinstance(found, BaseException):
            raise found
        return _Snap(found, f"t{self.n}")

    def update(self, payload, option=None):
        self.updates.append((dict(payload), option))
        if self.refuse:
            self.refuse -= 1
            import google.api_core.exceptions as gax
            raise gax.FailedPrecondition("the record changed")


class _Db:
    def __init__(self, record):
        self.record = record

    def collection(self, _name):
        return self.record

    def transaction(self, **_k):
        # What the rules answer this machine: BeginTransaction refused.
        import google.api_core.exceptions as gax
        raise gax.PermissionDenied("403 Missing or insufficient permissions.")

    def write_option(self, **kw):
        return ("precondition", kw)


def _flip(monkeypatch, record):
    monkeypatch.setattr(research, "_firebase_db", _Db(record))
    monkeypatch.setattr(research, "_be_payload", lambda p: dict(p))
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    # What the transactional flip took from run_server (a tree from before
    # wave 15 needs it to reach its own answer, not a NameError).
    monkeypatch.setattr(research, "_flip_txn_stage", lambda *_a: "", raising=False)
    return lift("_flip_queued_to_ongoing")("uid-sharer-w15", "chat_1790692602555_1")


def test_a_queued_record_is_flipped_with_no_transaction(monkeypatch):
    """⭐⭐ The 10-02 sharer's run: the flip now goes through. One read, one
    update — guarded by the record's update time from that read — and no
    transaction opened (the rules refuse this machine one)."""
    rec = _Record([{"status": "queued", "queuePosition": 1}])
    assert _flip(monkeypatch, rec) == "flipped"
    [(payload, option)] = rec.updates
    from google.cloud.firestore import DELETE_FIELD
    assert payload == {"status": "ongoing", "queuePosition": DELETE_FIELD,
                       "queuedBehindRunId": DELETE_FIELD, "queuedBehindTitle": DELETE_FIELD}
    assert option == ("precondition", {"last_update_time": "t1"})


@pytest.mark.parametrize("status", ["stopped", "ongoing", "cancelled"])
def test_a_record_that_is_no_longer_queued_is_left_as_it_is(monkeypatch, status):
    """The cancel race still wins: nothing is written over another status."""
    rec = _Record([{"status": status}])
    assert _flip(monkeypatch, rec) == f"skipped({status})"
    assert rec.updates == []


def test_a_record_written_under_the_flip_is_read_again(monkeypatch):
    """A cancel lands between the read and the write: the precondition fails,
    the record is read again, and the cancel stands."""
    rec = _Record([{"status": "queued"}, {"status": "stopped"}], refuse_updates=1)
    assert _flip(monkeypatch, rec) == "skipped(stopped)"
    assert len(rec.updates) == 1 and rec.n == 2


def test_written_under_it_twice_hands_the_question_back_to_the_caller(monkeypatch):
    rec = _Record([{"status": "queued"}], refuse_updates=5)
    assert _flip(monkeypatch, rec) == "error"
    assert len(rec.updates) == 2


def test_a_missing_record_and_an_unreadable_one(monkeypatch):
    assert _flip(monkeypatch, _Record([None])) == "missing"
    import google.api_core.exceptions as gax
    assert _flip(monkeypatch, _Record([gax.ServiceUnavailable("503")])) == "error"
