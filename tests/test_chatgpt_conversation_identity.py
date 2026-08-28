"""2026-08-05 prod incident — the ChatGPT leg reported on the wrong topic.

Run `NemoClaw_vs_NemoHermes_vs_Nemotron_..._20260805_064715`, backend v0.1.12.
`documents/chatgpt.md` came back 121KB about GOLDEN RETRIEVERS: 46 hits for
"golden retriever", 0 for any term in the run's own topic. Claude and Gemini
were clean. The leg logged `status=done`, the document became source 3-of-3 in
the NotebookLM notebook, and Phase 3 generated audio from it.

WHAT ACTUALLY HAPPENED (and it is not what the first read said):

  * The `client-side New chat` at 07:01:11 DID work. `_chatgpt_force_new_chat`
    already re-reads the URL and refuses a tab still on `/c/`, and the caller's
    failure line is absent from the log — so the tab was genuinely on a fresh
    composer at that instant.
  * That proof then had ZERO lifetime. Between it and the send the run does DR
    setup, a CUA/Vision setup ladder, a file attach, prompt typing, a DR
    re-activation and a chat-mode park — and nothing re-read the URL.
  * Playwright could not find Send (07:01:58), so a vision agent with a real
    mouse drove the tab (07:02:04). By 07:04:00 the page was showing a completed
    23-minute report on an unrelated topic.
  * `links.json` recorded `/c/6a72ce1e-…`. ChatGPT encodes creation time in the
    id's first group: that decodes to 2026-08-05 05:46:06Z — the previous
    evening in the operator's timezone. The P1 conversation `6a733ef8` decodes to
    2026-08-05 13:47:36Z,
    matching the observed P1 start to the second, which is what validates the
    method rather than assuming it.
  * Nothing downstream compared anything. `"chatgpt.com/c/" in url` was used at
    two sites as positive PROOF the brief had been submitted — so the code
    asserted health from the very fact that proved the failure.

The comment above Gemini's landing check has stated the principle since
2026-06-23: "the URL advances to /app/<id> — the reliable signal: every healthy
run gets one, a dropped send never does." It was applied to one platform out of
three. ChatGPT gives a STRONGER signal than Gemini — not just "in a
conversation" but "in one created at time T" — and it went unused.

Run:  pytest tests/test_chatgpt_conversation_identity.py -v
"""
import inspect
import json
import os
import sys
import time
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research
from _domshim import NODE, el, evaluate_js, run_js
from conftest import code_only_deep

# The two REAL conversation ids from the incident.
STALE = "https://chatgpt.com/c/6a72ce1e-2284-83ea-abcb-acdf3db558b0"   # 2026-08-05 05:46:06Z
FRESH = "https://chatgpt.com/c/6a733ef8-1111-2222-3333-444444444444"   # 2026-08-05 13:47:36Z
# ⚠ Deliberately NAIVE, i.e. local — do not "fix" this to UTC. It mirrors what
# production does: a run id carries `_%Y%m%d_%H%M%S` stamped by the machine in its
# own zone, and `_run_start_epoch` reads it back with a naive `strptime`. Pinning
# this to UTC makes the test disagree with the code it is testing, which is exactly
# what happened on the first attempt at the timezone fix above — two tests that
# compare a decoded directory stamp against this constant started failing.
#
# The distinction that matters: the ChatGPT conversation id encodes a true UTC
# instant, so the assertion above must name UTC. A run-id directory name encodes a
# LOCAL wall clock, so this must not.
RUN_START = datetime(2026, 8, 5, 6, 47, 15).timestamp()

needs_node = pytest.mark.skipif(NODE is None, reason="node required to run page JS")


# ── The decoder, against ground truth ─────────────────────────────────────

def test_the_decoder_reproduces_both_incident_timestamps():
    """If this drifts, every other guard here is built on sand.

    ⚠ Asserted in UTC, and against the epoch itself. The first version formatted
    with `datetime.fromtimestamp(...)` — LOCAL time — and compared it to strings
    that were only correct in the timezone they were written in. It passed on the
    machine that wrote it and failed in CI, which runs UTC: the same instant reads
    as 22:46 on 4 August in one place and 05:46 on the 5th in the other.

    A test whose verdict depends on where it runs is not a guard. The epoch is the
    value the decoder actually returns, so that is what is pinned; the UTC
    rendering is kept beside it because a bare integer is unreviewable.
    """
    assert research._chatgpt_convo_epoch(STALE) == 1785908766
    assert research._chatgpt_convo_epoch(FRESH) == 1785937656

    def when_utc(u):
        return datetime.fromtimestamp(research._chatgpt_convo_epoch(u), timezone.utc) \
            .strftime("%Y-%m-%d %H:%M:%S")
    assert when_utc(STALE) == "2026-08-05 05:46:06"
    assert when_utc(FRESH) == "2026-08-05 13:47:36"


@pytest.mark.parametrize("url", [
    "https://chatgpt.com/",
    "https://chatgpt.com/gpts",
    "https://chatgpt.com/share/6a72ce1e-2284-83ea",   # read-only view, not ours
    "https://chatgpt.com/c/",
    "https://chatgpt.com/c/short-1111",               # first group is not 8 chars
    "https://chatgpt.com/c/6a72ce1-1111-2222",        # 7 hex chars
    "https://chatgpt.com/c/6a72ce1ea-1111-2222",      # 9 hex chars
    "https://chatgpt.com/c/zzzzzzzz-1111-2222",       # not hex
    "https://chatgpt.com/c/00000001-1111-2222",       # decodes to 1970 — coincidence
    "https://chatgpt.com/c/ffffffff-1111-2222",       # decodes to 2106 — coincidence
    "",
    None,
])
def test_anything_that_is_not_a_conversation_id_decodes_to_none(url):
    assert research._chatgpt_convo_epoch(url) is None


def test_the_sanity_bound_subsumes_the_length_check():
    """⭐ AN HONEST NOTE, recorded rather than papered over. Mutation testing
    showed that deleting the `len(head) != 8` guard changes NO behaviour: the
    largest 7-hex-digit value is 268,435,455 (below the 1.6e9 floor) and the
    smallest 9-digit one is 4,294,967,296 (above the 4e9 ceiling), so no
    wrong-length hex string can land inside the plausible-date window. The length
    check is redundant belt, not a load-bearing gate — kept because it is free and
    states the format's shape, but nobody should believe a test proves it.

    This assertion pins the arithmetic the claim rests on, so if the bounds are
    ever widened the redundancy stops being true and this fails."""
    assert 0xFFFFFFF < 1_600_000_000, "a 7-digit id could now pass the floor"
    assert 0x100000000 > 4_000_000_000, "a 9-digit id could now pass the ceiling"


def test_query_and_fragment_do_not_defeat_the_decode():
    assert research._chatgpt_convo_epoch(STALE + "?model=gpt-5#foo") \
        == research._chatgpt_convo_epoch(STALE)


# ── Is this conversation ours? ────────────────────────────────────────────

def test_the_incident_conversation_is_rejected():
    assert research._chatgpt_conversation_is_ours(STALE, RUN_START) is False


def test_this_runs_conversation_is_accepted():
    assert research._chatgpt_conversation_is_ours(FRESH, RUN_START) is True


def test_an_unreadable_id_fails_closed():
    """No id, no permission. An unparseable URL must never read as ours."""
    for u in ("https://chatgpt.com/", "https://chatgpt.com/share/abc", "", None):
        assert research._chatgpt_conversation_is_ours(u, RUN_START) is False


def test_an_unknowable_run_start_fails_open():
    """The opposite bias, deliberately: if we cannot date the RUN we must not
    start failing healthy legs. Only the conversation side fails closed."""
    assert research._chatgpt_conversation_is_ours(STALE, None) is True


def test_the_slack_covers_clock_skew_but_not_a_stale_thread():
    convo = research._chatgpt_convo_epoch(FRESH)
    slack = research._CONVO_AGE_SLACK_SEC
    # Minted a minute BEFORE the run start — skew, still ours.
    assert research._chatgpt_conversation_is_ours(FRESH, convo + slack - 1) is True
    # Minted well before — not ours.
    assert research._chatgpt_conversation_is_ours(FRESH, convo + slack + 1) is False


def test_the_slack_is_far_smaller_than_the_incidents_staleness():
    """A slack big enough to admit the incident would make the guard decorative:
    the stale thread was ~8 hours old."""
    gap = research._chatgpt_convo_epoch(FRESH) - research._chatgpt_convo_epoch(STALE)
    assert research._CONVO_AGE_SLACK_SEC < gap / 10


# ── Dating the run ────────────────────────────────────────────────────────

def _with_run_dir(monkeypatch, tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    monkeypatch.setattr(research, "_p2_run_dir", lambda: d)
    return d


def test_run_start_takes_the_earliest_stamp_not_the_config_mtime(monkeypatch, tmp_path):
    """⚠ REVISED 2026-08-05. This used to assert the config mtime WINS, on the stated
    premise that "config.json is written once in the new-run branch (a resume only
    reads it)". That premise is false: `_write_config_to_disk` rewrites the file on any
    mid-run setting change, and the resume path merges its payload in. Either moves the
    mtime forward to now — making a mutable file the definition of "this run" and
    turning every conversation the run had already created into a foreign one.

    The sources must DISAGREE or the choice is unobservable, which is what the earlier
    version of this test got right and is kept here.
    """
    d = _with_run_dir(monkeypatch, tmp_path, "Topic_20260805_064715")
    cfg = d / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    later = RUN_START + 20 * 60          # the user changed a setting 20 min in
    os.utime(cfg, (later, later))
    got = research._run_start_epoch()
    assert got == pytest.approx(RUN_START, abs=1), (
        "a mid-run config rewrite must not move the run's start forward")
    assert abs(got - later) > 60, "the mutable mtime answered instead"


def test_a_config_written_before_the_directory_stamp_still_counts(monkeypatch, tmp_path):
    """The other direction — min() means whichever is EARLIER wins, not a fixed
    order. Reading too early only widens the window a conversation counts as ours,
    which is the safe failure."""
    d = _with_run_dir(monkeypatch, tmp_path, "Topic_20260805_070000")
    cfg = d / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    os.utime(cfg, (RUN_START, RUN_START))
    assert research._run_start_epoch() == pytest.approx(RUN_START, abs=1)


def test_run_start_uses_the_directory_stamp_when_it_is_alone(monkeypatch, tmp_path):
    """The immutable anchor, and every producer of a run id stamps it."""
    _with_run_dir(monkeypatch, tmp_path, "Topic_20260805_064715")
    assert research._run_start_epoch() == pytest.approx(RUN_START, abs=1)


def test_a_healthy_leg_survives_a_setting_change_mid_run(monkeypatch, tmp_path):
    """The regression this fix exists to prevent, stated end to end. The poll-path
    sweep runs every tick, so a mutable run start would have killed a live leg the
    moment the user touched a setting."""
    d = _with_run_dir(monkeypatch, tmp_path, "Topic_20260805_064715")
    ours = "https://chatgpt.com/c/6a7377d5-8f14-8320-a5d5-7f9a5a5f0f10"   # 10:50:13
    assert research._chatgpt_tab_is_foreign(ours) is False
    cfg = d / "config.json"
    cfg.write_text('{"agents": {"chatgpt": true}}', encoding="utf-8")
    os.utime(cfg, (research._chatgpt_convo_epoch(ours) + 3600,) * 2)
    assert research._chatgpt_tab_is_foreign(ours) is False, (
        "a mid-run config write made the leg's own conversation look foreign")


def test_run_start_falls_back_to_meta_created_at(monkeypatch, tmp_path):
    d = _with_run_dir(monkeypatch, tmp_path, "no-stamp-here")
    (d / "meta.json").write_text(json.dumps({"createdAt": int(RUN_START * 1000)}),
                                 encoding="utf-8")
    assert research._run_start_epoch() == pytest.approx(RUN_START, abs=1)


def test_run_start_is_none_when_nothing_can_date_it(monkeypatch, tmp_path):
    _with_run_dir(monkeypatch, tmp_path, "no-stamp-here")
    assert research._run_start_epoch() is None


def test_run_start_is_none_with_no_run_dir(monkeypatch):
    monkeypatch.setattr(research, "_p2_run_dir", lambda: None)
    assert research._run_start_epoch() is None


def test_a_real_run_dir_name_dates_to_its_own_stamp(monkeypatch, tmp_path):
    """The incident's actual directory name."""
    _with_run_dir(monkeypatch, tmp_path,
                  "NemoClaw_vs_NemoHermes_vs_Nemotron_and_also_about__20260805_064715")
    got = research._run_start_epoch()
    assert datetime.fromtimestamp(got).strftime("%Y-%m-%d %H:%M:%S") == "2026-08-05 06:47:15"


# ── The landing assertion ─────────────────────────────────────────────────

SEND_SRC = code_only_deep(research.start_agent_no_gemini_wait)


def test_chatgpt_now_has_a_landing_assertion_at_all():
    assert '_chatgpt_landed' in SEND_SRC, (
        "ChatGPT still returns True straight off the Send click"
    )


def test_the_landing_assertion_runs_before_the_function_can_return_true():
    i_land = SEND_SRC.index("_cg_ok, _cg_url, _cg_why = await _chatgpt_landed")
    # Anchor on the Gemini LANDING block (there is an earlier, unrelated
    # `platform_l == "gemini"` branch in this function), and on the tail return.
    assert i_land < SEND_SRC.index("def _gemini_in_conversation()")
    assert i_land < SEND_SRC.rindex("return page, True")


def test_a_failed_landing_fails_the_agent_rather_than_proceeding():
    tail = SEND_SRC[SEND_SRC.index("_cg_ok, _cg_url, _cg_why"):]
    branch = tail[:tail.index('if platform_l == "gemini":')]
    assert "if not _cg_ok:" in branch
    assert "fail_agent(" in branch, "a leg that never landed must not proceed"
    assert "return page, False" in branch
    # …and it must not leave a chat-mode card asking the user to keep output
    # from a send that never happened.
    assert "chat_mode_pending.pop" in branch


def test_the_landing_assertion_rejects_all_three_failure_shapes():
    """⚠ Assert on the CONDITIONS, not on the reason strings. A mutant that
    replaced the same-URL test with `if False:` left every reason string in place
    and passed the first version of this test — the label is not the check.

    ⛔⛔ RE-POINTED 2026-08-27, AND THE RE-POINTING IS THE LESSON. Every assertion
    below used to read the decision as INLINE SOURCE inside the loop — and source
    text cannot tell you that a guard fails closed on an input nobody thought of.
    It did: `/c/WEB:<uuid>` decoded to nothing, the identity check refused it, and
    a healthy leg died seven seconds after Send with this file entirely green.

    The decision now lives in `_chatgpt_landing_verdict`, a pure module-level
    function, and the real coverage is behavioural in
    `tests/test_chatgpt_landing_0827.py`. What is left here is the WIRING: that
    the loop delegates, and that each rejection still returns False.
    """
    src = SEND_SRC[SEND_SRC.index("async def _chatgpt_landed"):]
    src = src[:src.index("_cg_ok, _cg_url, _cg_why")]
    # The loop asks the pure function rather than deciding inline.
    assert "_verdict = _chatgpt_landing_verdict(_last, _pre_send_url)" in src, (
        "the loop must delegate the decision, not re-implement it"
    )
    # (1) the send left us on the conversation we were already on
    assert 'if _verdict == "unchanged":' in src, (
        "a send that created nothing must not read as landed"
    )
    assert "url_unchanged_from_pre_send" in src
    # (2) the conversation is one this run did not create
    assert 'if _verdict == "foreign":' in src, (
        "landing in A conversation is not landing in OURS"
    )
    assert "conversation_predates_this_run" in src
    # (3) no conversation at all — ⚠ THIS ONE MOVED. It is produced by
    # `_chatgpt_landing_result` once the wait budget is spent, not inside the
    # loop, so it is read from that function. Leaving it scoped to the loop slice
    # turned this file red the moment the tail was extracted, which is a fair
    # warning about how brittle a source pin is.
    tail = code_only_deep(research._chatgpt_landing_result)
    assert "no_conversation_url" in tail
    assert "undatable_id_transition_observed" in tail
    # ⭐ (4) THE NEW ONE: an id we cannot date must not fall into any of the
    # above. It keeps the budget running and is answered after the loop.
    assert 'if _verdict == "undatable":' in src
    assert "_undatable = _last" in src
    # …and each rejection returns rather than falling through. Two live in the
    # loop; the third is the tail's, asserted above.
    assert src.count("return False, _last,") >= 2
    assert "return _chatgpt_landing_result(_undatable, _last)" in src


def test_the_pre_send_url_is_captured_before_the_send_not_after():
    assert SEND_SRC.index("_pre_send_url = _url_now()") < SEND_SRC.index("_send_sels = ["), (
        "the pre-send snapshot must precede the send, or it records the outcome"
    )


def test_the_cua_send_pass_has_a_url_tripwire():
    """The vision agent is the only actor with a real mouse on this tab and the
    only plausible author of the navigation. Its aim cannot be fixed from here;
    its blast radius can at least be recorded.

    ⚠ This test used to assert only that `_post_cua_url` and `_pre_send_url` both
    appeared in a window — which a mutation setting `_post_cua_url = _pre_send_url`
    passes trivially, because both names are still there. Presence of the
    comparison's operands is not the comparison. Pin the LIVE read.
    """
    tail = SEND_SRC[SEND_SRC.index("CUA send attempted") - 900:
                    SEND_SRC.index("CUA send attempted")]
    assert "_post_cua_url = _url_now()" in tail, (
        "the post-CUA URL must be read LIVE — comparing the pre-send snapshot "
        "against itself can never differ"
    )
    assert "if _post_cua_url != _pre_send_url:" in tail
    # …and it must actually say something when it fires.
    fired = tail[tail.index("if _post_cua_url != _pre_send_url:"):]
    assert "log(" in fired and "MOVED" in fired


# ── The two predicates that read "/c/" as health ──────────────────────────

def test_no_bare_c_substring_decides_liveness_any_more():
    """Scoped to the ASSIGNMENTS. The substring may still appear in a diagnostic
    that says the conversation is NOT ours — what must not come back is a
    liveness flag computed from it."""
    src = code_only_deep(inspect.getsource(research))
    assert '_chatgpt_alive = "chatgpt.com/c/" in' not in src, (
        "being in A conversation is being read as being in OURS again"
    )
    assert '"chatgpt.com/c/" in (_cg_entry.get' not in src
    for name in ("_chatgpt_alive =", "_cg_alive ="):
        i = src.index(name)
        assert "_chatgpt_conversation_is_ours" in src[i:i + 260], (
            f"{name} no longer decides on conversation identity"
        )


def test_both_liveness_sites_route_through_the_identity_helper():
    p2 = code_only_deep(research.run_phase2)
    assert p2.count("_chatgpt_conversation_is_ours(") >= 2, (
        "the 2A alive-handoff and the Free-tier probe must both check identity"
    )


# ── _chatgpt_force_new_chat ───────────────────────────────────────────────

NEWCHAT_MARK_JS = evaluate_js(research._chatgpt_force_new_chat, contains="MARK")


@needs_node
def test_the_new_chat_marker_never_lands_on_a_sidebar_conversation_row():
    """ChatGPT titles an UNTITLED conversation "New chat" in the sidebar, and
    those rows are <a href="/c/<id>">. The old document-wide text-equality
    fallback could click one — navigating the tab straight into an arbitrary old
    conversation, which is exactly the incident's outcome."""
    spec = el("body", {}, "", [
        el("nav", {}, "", [
            el("a", {"href": "/c/6a72ce1e-2284-83ea", "w": "200", "h": "40"}, "New chat"),
            el("a", {"href": "/c/deadbeef-0000-0000", "w": "200", "h": "40"}, "New chat"),
        ]),
        el("button", {"data-testid": "create-new-chat-button", "w": "40", "h": "40"}, ""),
    ])
    out = run_js(spec, NEWCHAT_MARK_JS, research._SR_CLICK_MARK)
    assert out["ret"] == '[data-testid="create-new-chat-button"]'


@needs_node
def test_with_no_real_button_a_conversation_row_is_still_refused():
    """The dangerous case: the real control is gone (selector rotation) and the
    only things reading "New chat" are conversation links. Marking nothing is
    correct — the caller falls back to a same-tab goto."""
    spec = el("body", {}, "", [
        el("nav", {}, "", [
            el("a", {"href": "/c/6a72ce1e-2284-83ea", "w": "200", "h": "40"}, "New chat"),
        ]),
    ])
    assert run_js(spec, NEWCHAT_MARK_JS, research._SR_CLICK_MARK)["ret"] == ""


@needs_node
def test_a_genuine_text_only_new_chat_control_is_still_matched():
    """The fallback must not be neutered — a rotated selector with a real
    non-link button still has to be found."""
    spec = el("body", {}, "", [
        el("button", {"w": "80", "h": "32"}, "New chat"),
    ])
    assert run_js(spec, NEWCHAT_MARK_JS, research._SR_CLICK_MARK)["ret"] == "text:new chat"


@needs_node
def test_the_marker_is_cleared_before_a_new_one_is_placed():
    """A marker left over from an earlier pass is something THIS pass would aim
    at — `_sr_real_click` selects by the attribute, so two marked elements means
    the press lands on whichever comes first in document order.

    ⚠ The return value cannot show this: it is the matched SELECTOR, which is
    identical whether or not the stale marker was cleared. So COUNT the markers
    after the pass. (The first version of this test asserted only on `ret` and a
    mutant deleting the clear passed it.)
    """
    spec = el("body", {}, "", [
        el("div", {research._SR_CLICK_MARK: "newchat", "w": "10", "h": "10"}, "stale"),
        el("button", {"data-testid": "create-new-chat-button", "w": "40", "h": "40"}, ""),
    ])
    # Wrap the production JS so we can observe the DOM it leaves behind.
    probe = ("(MARK) => { const ret = (" + NEWCHAT_MARK_JS + ")(MARK);"
             " return { ret, marks: document.querySelectorAll('[' + MARK + ']').length }; }")
    out = run_js(spec, probe, research._SR_CLICK_MARK)["ret"]
    assert out["ret"] == '[data-testid="create-new-chat-button"]'
    assert out["marks"] == 1, (
        f"{out['marks']} elements carry the click marker — a stale one from an "
        f"earlier pass is still there, and the press aims at document order"
    )


def test_the_new_chat_click_is_a_real_press_not_a_synthetic_one():
    src = code_only_deep(research._chatgpt_force_new_chat)
    assert "_sr_real_click(" in src, (
        "a synthetic el.click() inside page.evaluate does not open ChatGPT's "
        "React controls — mark in JS, press with Playwright"
    )
    assert "el.click()" not in src


def test_a_fresh_composer_now_means_an_empty_thread():
    src = code_only_deep(research._chatgpt_force_new_chat)
    assert "data-message-author-role" in src, (
        "the composer selector is true on a conversation page too — emptiness "
        "is the question that separates a fresh chat from someone else's thread"
    )


def test_the_new_chat_decision_logs_the_url_it_decided_on():
    """The check had already run and passed in the incident, and nobody could
    see that, because it decided on a URL it never logged."""
    src = code_only_deep(research._chatgpt_force_new_chat)
    assert src.count("New-chat check: url") >= 2, (
        "log the URL both before and after the press"
    )
