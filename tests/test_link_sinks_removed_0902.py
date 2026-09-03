"""STRETCH 7.5 STEP 5 — the conversation address stops leaving this machine.

⛔⛔ WHAT WAS HAPPENING, ON FOUR CHANNELS AT ONCE. Each agent's conversation
address — a page that opens for nobody but the account that ran it — was:

  1. streamed to the app inside every `pipeline_paused` event, persisted to the
     event log for thirty days, and handed to a MODEL by the follow-up chat's
     recent-events tool, which filters progress noise and nothing else;
  2. written into the research record as `links.brief`, stamped `verified=True`,
     by a direct Firestore write that never passes the module's own deny list —
     the one that names `chatgpt.com/c/` as a shape that must never be emitted;
  3. mirrored, unguarded, into `delivery.json` at the end of phase 2, which the
     local run server returns verbatim to any caller on any interface;
  4. printed in full into the run log, which send-logs zips and uploads.

⭐ AND NOT ONE OF THOSE WAS A LINE THAT PUBLISHED A LINK. Three of the four were
justified by comments describing consumers that no longer exist, and the fourth
was pinned as a FEATURE by a test whose stated reason — "so the app can show the
run" — is not something the app does. That inverted guard is in
tests/test_pause_resume_safety_net_0902.py; the mutant that scored its removal as
a defect is P2, now inverted with it.

⚠ WHAT DELIBERATELY DID NOT CHANGE. The address is the pause/resume REATTACHMENT
KEY: on resume each still-running agent's tab is re-opened at its saved address,
and an agent restored without one comes back with no page, which the next poll
tick's crash sweep reads as a browser crash and deletes from the run. So the
checkpoint on disk keeps every field; only the wire gets less. The pairing is
asserted here and in the safety net, from both ends.

Run:  pytest tests/test_link_sinks_removed_0902.py -v
"""
import asyncio
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research
from conftest import code_only

REPO = Path(__file__).resolve().parents[1]

CHATGPT_URL = "https://chatgpt.com/c/68b1a0f0-1111-2222-3333-444455556666"
GEMINI_URL = "https://gemini.google.com/app/9f41418747cf4a36"
CLAUDE_URL = "https://claude.ai/chat/aaaa1111-bbbb-2222-cccc-333344445555"
PRIVATE = (CHATGPT_URL, GEMINI_URL, CLAUDE_URL)

RID = "rid_step5"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    research._runtime.reset()
    monkeypatch.setattr(research, "_fb_research_id", RID)
    yield
    research._runtime.reset()


# ═════════════════════════════════════════════════════════════════════════════
# 1 — the address that replaced it: our own document page
# ═════════════════════════════════════════════════════════════════════════════

def test_the_in_app_page_names_the_run_and_the_document(monkeypatch):
    assert research.in_app_document_url("brief") == f"/documents?open={RID}:brief"
    assert research.in_app_document_url("chatgpt") == f"/documents?open={RID}:chatgpt"


def test_two_documents_of_one_run_never_collapse_to_the_same_page():
    """⛔ A helper that returned one answer for every kind would satisfy every
    "starts with /documents" check in this file and lose which report is which."""
    kinds = ("brief", "chatgpt", "gemini", "claude", "consolidated")
    answers = {research.in_app_document_url(k) for k in kinds}
    assert len(answers) == len(kinds)


def test_it_is_a_path_on_our_own_origin_and_never_an_address_elsewhere():
    """⭐ THE PROPERTY THAT MAKES IT SAFE AT EVERY SINK. An in-app page cannot be
    a private chat, cannot be published anywhere useful to a stranger, and needs
    no deny list — because it names no host at all."""
    for kind in ("brief", "chatgpt", ""):
        url = research.in_app_document_url(kind)
        assert url.startswith("/")
        assert "://" not in url


@pytest.mark.parametrize("rid,kind,expected", [
    ("", "brief", "/documents"),
    (None, "brief", "/documents"),
    (RID, "", "/documents"),
    (RID, None, "/documents"),
])
def test_either_half_missing_falls_back_to_the_index(monkeypatch, rid, kind, expected):
    """⛔ BOTH HALVES, because either one alone produces a link that goes nowhere:
    no id gives `/documents?open=:brief` and no kind gives `/documents?open=<id>:`.
    A run with neither is a CLI run, which is a supported way to use this."""
    monkeypatch.setattr(research, "_fb_research_id", rid)
    assert research.in_app_document_url(kind) == expected


# ═════════════════════════════════════════════════════════════════════════════
# 2 — the log lines: redacted, not removed
# ═════════════════════════════════════════════════════════════════════════════

def test_the_redaction_keeps_the_platform_and_the_kind_of_page():
    """A log line exists to answer "which tab was this leg on". Dropping the line
    answers nothing; dropping the identifier still answers most of it."""
    out = research.redacted_chat_url(CHATGPT_URL)
    assert out.startswith("chatgpt.com/c/")
    out_g = research.redacted_chat_url(GEMINI_URL)
    assert out_g.startswith("gemini.google.com/app/")


def test_the_identifier_itself_never_survives():
    """⭐ THE UNIVERSAL. Not "the output is short" — the output must not contain
    the part of the address that identifies the conversation."""
    for url in PRIVATE:
        out = research.redacted_chat_url(url)
        ident = url.rstrip("/").rsplit("/", 1)[-1]
        assert ident not in out, url
        assert url not in out
        # And no run of the identifier long enough to search for survives either.
        assert not any(ident[i:i + 8] in out for i in range(max(1, len(ident) - 7)))


def test_the_same_tab_reads_the_same_twice_and_two_tabs_never_read_alike():
    """The whole point of keeping a digest: two log lines about one tab can still
    be tied together, and two tabs can still be told apart."""
    assert research.redacted_chat_url(CHATGPT_URL) == research.redacted_chat_url(CHATGPT_URL)
    other = CHATGPT_URL[:-1] + "7"
    assert research.redacted_chat_url(CHATGPT_URL) != research.redacted_chat_url(other)


def test_an_empty_address_stays_empty():
    assert research.redacted_chat_url("") == ""
    assert research.redacted_chat_url(None) == ""


def test_an_address_the_parser_refuses_is_still_redacted():
    """⛔⛔ FALLING THROUGH TO THE RAW STRING ON A PARSE FAILURE WOULD MAKE A
    MALFORMED ADDRESS THE BYPASS — the same trap the app-side predicate records.

    ⛔⛔ AND MY FIRST FIXTURE HERE NEVER REACHED THE BRANCH IT WAS TESTING. It used
    `https://chatgpt.com:99999999/c/abc123`, copied from the app-side guard where a
    port over 65535 makes the browser's URL parser throw. Measured in Python:
    `urlsplit(...).hostname` returns `chatgpt.com` quite happily — only `.port`
    raises, and this code never asks for it. So the redaction took the normal path,
    the assertions passed, and the mutant that made a parse failure return the raw
    address SURVIVED. A borrowed fixture is not a measured one.

    ▶ `http://[/c/abc` is what actually raises here (Invalid IPv6 URL). Both are
    kept: one proves the fallback, the other proves the ordinary path still handles
    an address the app-side rules would call malformed."""
    unparseable = "http://[/c/abc"
    out = research.redacted_chat_url(unparseable)
    assert unparseable not in out
    assert "/c/abc" not in out
    assert out.startswith("<url #")

    odd_port = "https://chatgpt.com:99999999/c/abc123"
    out2 = research.redacted_chat_url(odd_port)
    assert "abc123" not in out2
    assert odd_port not in out2
    assert out2.startswith("chatgpt.com/c/")


def test_both_log_lines_that_named_a_tab_go_through_it():
    """⚠ SOURCE PINS, and they say so: neither the resume loop nor the poll loop
    can be driven by this suite. The redactor itself is executed above."""
    resume = code_only(inspect.getsource(research.resume_browser_from_checkpoint))
    assert "redacted_chat_url(url)" in resume
    assert "{url[:80]}" not in resume
    poll = code_only(inspect.getsource(research.poll_all_agents_round_robin))
    assert "convo={redacted_chat_url(" in poll
    assert "convo={(res.get('url') or '')[:60]}" not in poll


# ═════════════════════════════════════════════════════════════════════════════
# 3 — the pause snapshot: the disk keeps it, the wire does not
# ═════════════════════════════════════════════════════════════════════════════

def _three_agents():
    research._runtime.agent_chat_urls = {
        "chatgpt": CHATGPT_URL, "gemini": GEMINI_URL, "claude": CLAUDE_URL}
    research._runtime.agent_statuses = {
        "chatgpt": "generating", "gemini": "generating", "claude": "done"}
    research._runtime.phase = 2


def test_the_app_view_drops_the_reconnect_key_and_keeps_the_rest():
    _three_agents()
    full = research._runtime.snapshot()
    app = research._runtime.snapshot_for_app()
    assert "agent_chat_urls" in full
    assert "agent_chat_urls" not in app
    assert set(full) - set(app) == {"agent_chat_urls"}
    for key in app:
        assert app[key] == full[key], key


def test_no_private_address_survives_anywhere_in_the_app_view():
    """⭐ THE UNIVERSAL, not the one key. A future field carrying the same value
    under another name is the way this comes back."""
    _three_agents()
    research._runtime.original_inputs = {"topic": "quantum error correction"}
    blob = json.dumps(research._runtime.snapshot_for_app())
    for url in PRIVATE:
        assert url not in blob, url


def test_the_full_snapshot_is_untouched_because_the_checkpoint_reads_it():
    """⛔⛔ THE PAIRING. Stripping inside `snapshot()` satisfies every assertion
    above and costs an agent on every resume: the pause checkpoint is built from
    the same call, and the resume loop re-opens each still-running agent's tab at
    the address it finds there."""
    _three_agents()
    full = research._runtime.snapshot()
    assert full["agent_chat_urls"]["gemini"] == GEMINI_URL
    assert full["agent_chat_urls"]["chatgpt"] == CHATGPT_URL


def test_the_local_only_list_is_what_decides_it_not_a_hardcoded_key():
    """A second field added to the list must actually be dropped — otherwise the
    list is decoration and the next value ships."""
    _three_agents()
    research._runtime.__class__._SNAPSHOT_LOCAL_ONLY = ("agent_chat_urls", "agent_statuses")
    try:
        app = research._runtime.snapshot_for_app()
        assert "agent_statuses" not in app
        assert "phase" in app
    finally:
        research._runtime.__class__._SNAPSHOT_LOCAL_ONLY = ("agent_chat_urls",)


def test_the_pause_emit_asks_for_the_app_view():
    src = code_only(inspect.getsource(research.pause_and_close_browser))
    assert "snapshot=_runtime.snapshot_for_app()" in src
    assert "snapshot=_runtime.snapshot()" not in src


# ═════════════════════════════════════════════════════════════════════════════
# 4 — the research record's brief slot
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def aggregate(monkeypatch):
    seen = []
    monkeypatch.setattr(research, "update_link_in_firestore",
                        lambda kind, url, **kw: seen.append((kind, url, kw)))
    return seen


def test_the_brief_slot_is_filled_with_our_own_page(aggregate):
    research._record_brief_in_aggregate(research.in_app_document_url("brief"))
    assert aggregate == [("brief", f"/documents?open={RID}:brief",
                          {"label": "Research Brief", "phase": 1, "verified": True})]


def test_nothing_is_written_when_there_is_no_page(aggregate):
    research._record_brief_in_aggregate("")
    research._record_brief_in_aggregate(None)
    assert aggregate == []


def test_a_firestore_failure_does_not_end_the_run(monkeypatch):
    """Every other Firestore write on the phase-1 path is best-effort; a
    convenience slot must not be the one that raises."""
    def _boom(*a, **kw):
        raise RuntimeError("grpc unavailable")
    monkeypatch.setattr(research, "update_link_in_firestore", _boom)
    research._record_brief_in_aggregate("/documents?open=x:brief")  # must not raise


def test_all_three_brief_branches_record_the_page_and_none_records_an_address():
    """⛔ THE UNIVERSAL over phase 1. Before step 5 exactly one branch wrote the
    slot and what it wrote was the ChatGPT tab. Three branches write it now, and
    the argument is the same expression in each."""
    src = code_only(inspect.getsource(research.run_pipeline))
    assert src.count("_record_brief_in_aggregate(") == 3
    assert 'update_link_in_firestore("brief"' not in src
    for arg in ("_record_brief_in_aggregate(_in_app_brief_url)",
                "_record_brief_in_aggregate(_regen_in_app_url)"):
        assert arg in src, arg


def test_the_pipeline_never_binds_the_conversation_address_to_the_brief_name():
    """⛔⛔ THE ROOT CAUSE, PINNED. `brief_url` used to mean the brief's own page
    on three branches and the ChatGPT tab on the fourth, and every sink downstream
    — the record, the phase-2 and phase-3 checkpoints, the pause hand-off — took
    whichever it was handed. One name, one meaning."""
    src = code_only(inspect.getsource(research.run_pipeline))
    assert 'brief_url = p1.get("url", "")' not in src
    assert 'brief_url = p1_new.get("url", brief_url)' not in src
    for good in ("brief_url = _in_app_brief_url", "brief_url = _regen_in_app_url"):
        assert good in src, good


# ═════════════════════════════════════════════════════════════════════════════
# 5 — the phase-2 → phase-3 hand-off and what it hands on
# ═════════════════════════════════════════════════════════════════════════════

def _run_dir(tmp_path):
    (tmp_path / "documents").mkdir()
    (tmp_path / "meta.json").write_text(json.dumps({"topic": "libkrun microVM"}),
                                        encoding="utf-8")
    return tmp_path


def test_what_is_published_is_never_a_value_that_arrived_on_results(tmp_path):
    """⭐ THE UNIVERSAL, stated against the INPUT rather than a fixed expectation:
    no published value may be anything the agents handed us."""
    run_dir = _run_dir(tmp_path)
    results = {n: {"status": "done", "text": "x" * 30_000, "url": u, "verified": True}
               for n, u in (("ChatGPT", CHATGPT_URL), ("Gemini", GEMINI_URL),
                            ("Claude", CLAUDE_URL))}
    research._build_phase2_to_phase3_handoff(results, run_dir)
    published = dict(research._runtime.p2_links_for_p3)
    assert len(published) == 3
    incoming = {r["url"] for r in results.values()}
    for name, url in published.items():
        assert url not in incoming
        assert url == research.in_app_document_url(name.lower())


def test_a_leg_that_never_reached_a_page_publishes_nothing(tmp_path):
    """⛔⛔ THE GATE STEP 5 MUST NOT LOSE, AND MUTATION IS WHAT FOUND IT MISSING.
    The hand-off publishes an address of ours now, which is available for every
    agent whether or not that agent ever opened a tab — so removing the
    `if _url:` gate would publish a row for a leg that never ran, and skip both
    drop guards on the way, because all three read the same value. Nothing in
    this file noticed until the mutant survived."""
    run_dir = _run_dir(tmp_path)
    results = {"ChatGPT": {"status": "done", "text": "x" * 30_000, "url": "",
                           "verified": True}}
    research._build_phase2_to_phase3_handoff(results, run_dir)
    assert dict(research._runtime.p2_links_for_p3) == {}


def test_a_leg_the_sweep_refused_publishes_nothing(tmp_path):
    """⛔ THE 2026-08-05 INCIDENT, ONE VALUE LATER. The sweep blanks the text and
    marks the result; the hand-off used to add the link anyway, because it reads
    the url on a line of its own. What is published changed; the drop must not."""
    run_dir = _run_dir(tmp_path)
    results = {"ChatGPT": {"status": "done", "text": "x" * 30_000, "url": CHATGPT_URL,
                           "verified": True, "off_topic_rejected": True}}
    research._build_phase2_to_phase3_handoff(results, run_dir)
    assert dict(research._runtime.p2_links_for_p3) == {}


def test_a_conversation_that_predates_the_run_publishes_nothing(tmp_path, monkeypatch):
    """⛔ THE BELT, and the reason it is worth having: the topic sweep is inert
    when the topic yields too few anchors or the text is under the size floor, so
    nothing gets marked rejected — but the tab is still provably not this run's."""
    run_dir = _run_dir(tmp_path)
    old = research._chatgpt_convo_epoch(CHATGPT_URL)
    monkeypatch.setattr(research, "_run_start_epoch",
                        lambda: old + 2 * research._CONVO_AGE_SLACK_SEC + 1.0)
    assert research._chatgpt_tab_is_foreign(CHATGPT_URL) is True, "precondition"
    results = {"ChatGPT": {"status": "done", "text": "x" * 30_000, "url": CHATGPT_URL,
                           "verified": True}}
    research._build_phase2_to_phase3_handoff(results, run_dir)
    assert dict(research._runtime.p2_links_for_p3) == {}
    # ⚠ And the belt is still scoped to the ChatGPT leg — running another
    # platform's address through a ChatGPT id decoder is a false positive that
    # costs a healthy leg its row.
    borrowed = {"Gemini": {"status": "done", "text": "x" * 30_000, "url": CHATGPT_URL,
                           "verified": True}}
    research._build_phase2_to_phase3_handoff(borrowed, run_dir)
    assert dict(research._runtime.p2_links_for_p3) == {
        "Gemini": research.in_app_document_url("gemini")}


def test_the_delivery_mirror_no_longer_gets_an_unguarded_second_copy():
    """⛔⛔ IT RAN BEFORE THE HAND-OFF, so neither the off-topic drop nor the age
    test had touched the values: a leg the sweep had just refused still had its
    address written to `delivery.json` under its own name — and the local run
    server returns that file verbatim, on every interface, with no auth."""
    src = code_only(inspect.getsource(research.run_pipeline))
    assert "update_delivery(research_links=agent_urls)" not in src
    assert 'agent_urls = {n: r.get("url", "")' not in src


def test_the_links_file_is_still_written_and_is_still_valid_json():
    """⛔ THE ONE THING STEP 5 MAY NOT DO. The file's EXISTENCE is the
    resume-from-phase-3 signal, and its single content read is a bare `json.loads`
    with no `except` — so a zero-byte or whitespace file passes the hand-off and
    then raises on a later resume. It is written as a serialized dict or not at
    all."""
    src = code_only(inspect.getsource(research.run_phase3_upload))
    assert "links_file.write_text(json.dumps(links, indent=2)" in src
    # And the resume rung still keys on existence alone — never on contents.
    resume = code_only(inspect.getsource(research.detect_resume_phase))
    assert '(queue_dir / "links.json").exists()' in resume
    assert "json.loads" not in resume.split('"links.json"')[1][:400]


# ═════════════════════════════════════════════════════════════════════════════
# 6 — the sweep: no sink anywhere still ships a shape the module itself bans
# ═════════════════════════════════════════════════════════════════════════════

def test_no_conversation_address_reaches_a_sink_this_step_owns(tmp_path):
    """⭐ END TO END over the three values a run holds. Build the state a real
    paused run has, drive the two functions that publish from it, and read every
    byte that leaves: not one may contain an address the deny list names."""
    _three_agents()
    run_dir = _run_dir(tmp_path)
    results = {n: {"status": "done", "text": "x" * 30_000, "url": u, "verified": True}
               for n, u in (("ChatGPT", CHATGPT_URL), ("Gemini", GEMINI_URL),
                            ("Claude", CLAUDE_URL))}
    research._build_phase2_to_phase3_handoff(results, run_dir)
    leaving = json.dumps({
        "paused": research._runtime.snapshot_for_app(),
        "links_file": dict(research._runtime.p2_links_for_p3),
    })
    for bad in research._BAD_URL_PATTERNS:
        assert bad not in leaving, bad


def test_the_deny_list_still_names_the_three_conversation_hosts():
    """⚠ The test above is only as strong as this list. If a host were dropped
    from it, that sweep would keep passing while the address it stopped naming
    shipped."""
    joined = " ".join(research._BAD_URL_PATTERNS)
    for shape in ("chatgpt.com/c/", "gemini.google.com/app", "claude.ai/chat/"):
        assert shape in joined, shape


def test_the_comments_that_justified_the_write_say_what_the_code_does_now():
    """⛔ THREE COMMENTS NAMED CONSUMERS THAT DO NOT EXIST — a Doc spec that
    requires the address, a phase dropdown that opens it, an aggregate that is
    P5's single source of truth. Prose is how the next person decides a write is
    load-bearing.

    ⚠ ASSERTED AS CORRECTIONS PRESENT, NOT AS OLD WORDS ABSENT — and my first
    draft got that wrong. A correction that quotes what it is correcting still
    contains the old sentence, so `not in` fails on the very comment that fixed
    it. The old wording is allowed to appear; asserting it as live is not.
    """
    agg = inspect.getsource(research.update_link_in_firestore)
    assert "Measured: neither string exists in the app" in agg
    assert "ACTUAL readers are four" in agg
    assert "AND THIS WRITER VALIDATES NOTHING" in agg
    emit = research.emit_validated_link.__doc__ or ""
    assert "single source of truth, no event-log replay needed" not in emit
    assert "It does not." in emit
    keep = inspect.getsource(research.PipelineRuntime.unregister_page)
    assert 'said "checkpoint/link display"' in keep
    assert "There is no link display" in keep
