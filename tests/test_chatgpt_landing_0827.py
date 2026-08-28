"""2026-08-27 — ChatGPT's `WEB:` conversation id killed a healthy leg in 7 seconds.

MEASURED FROM A REAL RUN, from the log bundle the owner sent (`6CB3MXQC`). Two
runs, the same code, three seconds apart:

    run 1, 3s after Send →  /c/WEB:c3a7026f-6c11-4179-9003-0ba4c93a18f3
    run 2, 3s after Send →  /c/6a90bef9-64b0-83e9-a0a6-adfdef1c0065

ChatGPT normally encodes creation time in the id's first group. `6a90bef9`
decodes to 22:49:29 — the exact second Send was pressed. `WEB:c3a7026f` decodes
to nothing: split on "-" it yields a 12-character head, not 8, so
`_chatgpt_convo_epoch` returns None. `_chatgpt_conversation_is_ours` fails CLOSED
on an unreadable id — correctly, for its own purpose — and the landing check read
that single False as "this conversation belongs to somebody else".

Run 1's Deep Research leg was declared foreign, auto-skipped, and dropped from the
Phase 2→3 handoff, SEVEN SECONDS into a 34-minute run. Run 2 got a normal id
inside the same three-second window and sailed through. **A race, not a
regression** — which is why it looked like an intermittent platform fault.

⛔⛔ THE ROOT CAUSE IS NOT THE PREFIX. It is that the wait loop stopped at the
first thing SHAPED like a conversation and then passed judgement, instead of
spending its own thirty-second budget looking for one it could identify.

⛔⛔ AND STRIPPING THE PREFIX WOULD NOT BE A FIX. `c3a7026f` as hex seconds is the
year 2074. It would have been accepted only because a random value happened to
land in the future; an id beginning `1a…` would decode to 1983 and be rejected all
over again. The tests below pin that reasoning so nobody "simplifies" it back.

The 2026-08-05 incident — a warm tab parked in the previous evening's finished
thread, harvested as this run's output — must stay caught, and does: that
conversation's id was perfectly readable and simply old. Datable-and-old is still
refused on sight. Only an id NOTHING can date reaches the fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402


# The two real ids from the bundle, and the incident's.
WEB = "https://chatgpt.com/c/WEB:c3a7026f-6c11-4179-9003-0ba4c93a18f3"
RUN2 = "https://chatgpt.com/c/6a90bef9-64b0-83e9-a0a6-adfdef1c0065"   # 22:49:29
RUN1_P1 = "https://chatgpt.com/c/6a9094bf-4b64-83ea-b405-55250cb665c4"  # 19:49:19
INCIDENT = "https://chatgpt.com/c/6a72ce1e-0000-4000-8000-000000000000"  # 2026-08-04
HOST = "https://chatgpt.com/"

RUN2_SENT_AT = 1787870969.0        # what 6a90bef9 decodes to
RUN2_STARTED = RUN2_SENT_AT - 400  # the run began before the send


class TestTheIdsThemselves:
    """The decode is the evidence for everything else here, so pin it."""

    def test_a_normal_id_decodes_to_the_second_send_was_pressed(self):
        assert research._chatgpt_convo_epoch(RUN2) == 1787870969
        assert research._chatgpt_convo_epoch(RUN1_P1) == 1787860159

    # ⛔⛔ THE WHOLE INCIDENT IN ONE ASSERTION.
    def test_the_web_prefixed_id_carries_no_time_at_all(self):
        assert research._chatgpt_convo_epoch(WEB) is None

    # ⭐ The id IS there — that is the distinction the old code could not make.
    def test_the_web_prefixed_id_is_still_a_conversation_id(self):
        assert research._chatgpt_convo_id(WEB) == "WEB:c3a7026f-6c11-4179-9003-0ba4c93a18f3"
        assert research._chatgpt_convo_id(RUN2) == "6a90bef9-64b0-83e9-a0a6-adfdef1c0065"

    def test_a_page_that_is_not_a_conversation_has_no_id(self):
        for u in (HOST, "https://chatgpt.com/share/abc", "https://chatgpt.com/g/g-x", ""):
            assert research._chatgpt_convo_id(u) is None, u

    # ⛔⛔ WHY WE DO NOT STRIP THE PREFIX. Left of the colon removed, the id
    # decodes to 2074 — it would pass the run-start comparison by luck.
    def test_stripping_the_prefix_would_decode_to_nonsense(self):
        stripped = "https://chatgpt.com/c/c3a7026f-6c11-4179-9003-0ba4c93a18f3"
        epoch = research._chatgpt_convo_epoch(stripped)
        assert epoch is not None and epoch > 3_000_000_000, (
            "if this ever decodes to a sane date the 'do not strip' argument needs re-checking"
        )


class TestTheLandingVerdict:
    """One observation of the URL after Send → one word."""

    def test_a_fresh_normal_conversation_is_ours(self):
        assert research._chatgpt_landing_verdict(RUN2, HOST, RUN2_STARTED) == "ours"

    # ⛔⛔ THE ONE THAT SHIPPED BROKEN. This used to come back "foreign".
    def test_an_undatable_id_is_not_a_verdict(self):
        assert research._chatgpt_landing_verdict(WEB, HOST, RUN2_STARTED) == "undatable"

    # ⛔⛔ THE 2026-08-05 INCIDENT MUST STAY CAUGHT.
    def test_a_datable_conversation_older_than_the_run_is_refused(self):
        assert research._chatgpt_landing_verdict(INCIDENT, HOST, RUN2_STARTED) == "foreign"

    def test_the_url_not_moving_means_the_send_created_nothing(self):
        assert research._chatgpt_landing_verdict(RUN2, RUN2, RUN2_STARTED) == "unchanged"

    # ⛔ "Unchanged" outranks "undatable": a send that created nothing is a
    # failure whatever the id looks like, and reading it as "keep waiting" would
    # burn the whole budget on a dead composer.
    def test_unchanged_wins_even_for_an_undatable_id(self):
        assert research._chatgpt_landing_verdict(WEB, WEB, RUN2_STARTED) == "unchanged"

    def test_a_query_string_does_not_make_it_a_new_conversation(self):
        assert research._chatgpt_landing_verdict(RUN2 + "?model=gpt", RUN2,
                                                 RUN2_STARTED) == "unchanged"

    def test_not_being_on_a_conversation_yet_is_not_a_failure(self):
        for u in (HOST, "", "https://chatgpt.com/share/xyz"):
            assert research._chatgpt_landing_verdict(u, HOST, RUN2_STARTED) == "no_conversation", u

    # ⛔ Fails OPEN on an unknowable run start — the pre-existing rule. If we
    # cannot date the RUN we must not start failing healthy legs.
    def test_an_unknowable_run_start_does_not_condemn_anything(self):
        assert research._chatgpt_landing_verdict(INCIDENT, HOST, None) in ("ours", "foreign")
        # With no run start the identity check cannot refuse, so it must not.
        assert research._chatgpt_conversation_is_ours(INCIDENT, None) is True


class TestTheForeignTabCheckOnThePollPath:
    """The same predicate runs every tick of the round-robin, so the same bug
    lived there too — a `WEB:` leg would have been killed mid-run even if setup
    had let it through."""

    def test_an_undatable_conversation_is_not_foreign(self):
        assert research._chatgpt_tab_is_foreign(WEB) is False

    def test_a_bare_host_is_not_foreign(self):
        assert research._chatgpt_tab_is_foreign(HOST) is False

    def test_a_datable_old_conversation_is_still_foreign(self, monkeypatch):
        monkeypatch.setattr(research, "_run_start_epoch", lambda: RUN2_STARTED)
        assert research._chatgpt_tab_is_foreign(INCIDENT) is True

    def test_our_own_conversation_is_not_foreign(self, monkeypatch):
        monkeypatch.setattr(research, "_run_start_epoch", lambda: RUN2_STARTED)
        assert research._chatgpt_tab_is_foreign(RUN2) is False


class TestTheWholeSequence:
    """Replay the two runs as the wait loop would see them, second by second."""

    @staticmethod
    def _drive(urls, pre, run_start):
        """The loop's decision logic, exactly: keep waiting through `undatable`,
        remember the last one, and fall back to it if the budget runs out."""
        undatable = ""
        last = ""
        for u in urls:
            last = u
            verdict = research._chatgpt_landing_verdict(u, pre, run_start)
            if verdict == "unchanged":
                return False, u, "url_unchanged_from_pre_send"
            if verdict == "ours":
                return True, u, "ok"
            if verdict == "foreign":
                return False, u, "conversation_predates_this_run"
            if verdict == "undatable":
                undatable = u
        # ⛔ THE REAL FUNCTION, not a re-implementation of it. Modelling this tail
        # inline is what let a mutant delete the whole fallback and survive.
        return research._chatgpt_landing_result(undatable, last)

    # ⛔⛔ RUN 1, AS IT ACTUALLY HAPPENED. It must now succeed.
    def test_run_one_now_lands(self):
        ok, url, why = self._drive([HOST, HOST, WEB, WEB, WEB], HOST, RUN2_STARTED)
        assert ok is True
        assert url == WEB
        assert why == "undatable_id_transition_observed"

    def test_run_two_still_lands_immediately_and_by_the_strong_route(self):
        ok, url, why = self._drive([HOST, HOST, RUN2], HOST, RUN2_STARTED)
        assert (ok, url, why) == (True, RUN2, "ok")

    # ⭐ THE RACE, RESOLVED THE RIGHT WAY ROUND. If the placeholder is transient
    # and the real id arrives later in the window, we take the REAL one — the
    # strong evidence — not the fallback.
    def test_a_placeholder_that_resolves_is_confirmed_by_the_real_id(self):
        ok, url, why = self._drive([HOST, WEB, WEB, RUN2], HOST, RUN2_STARTED)
        assert (ok, url, why) == (True, RUN2, "ok")

    # ⛔⛔ AND THE INCIDENT STILL DIES ON SIGHT, even though the URL did change
    # from the pre-send one. This is the assertion that stops the fallback from
    # quietly re-opening 2026-08-05.
    def test_a_foreign_conversation_is_refused_and_never_reaches_the_fallback(self):
        ok, url, why = self._drive([HOST, INCIDENT, INCIDENT], HOST, RUN2_STARTED)
        assert ok is False
        assert why == "conversation_predates_this_run"

    def test_a_foreign_conversation_is_refused_even_after_an_undatable_one(self):
        ok, _u, why = self._drive([WEB, INCIDENT], HOST, RUN2_STARTED)
        assert ok is False and why == "conversation_predates_this_run"

    def test_a_send_that_never_leaves_the_composer_still_fails(self):
        ok, _u, why = self._drive([HOST, HOST, HOST], HOST, RUN2_STARTED)
        assert ok is False and why == "no_conversation_url"

    def test_a_send_that_never_moved_off_its_conversation_still_fails(self):
        ok, _u, why = self._drive([RUN2, RUN2], RUN2, RUN2_STARTED)
        assert ok is False and why == "url_unchanged_from_pre_send"


class TestTheBudgetRunningOut:
    """The tail of the wait loop, on its own.

    ⛔⛔ MUTATION FOUND THIS UNCOVERED. A mutant that replaced the fallback's
    condition with `if False:` — deleting the headline of the whole fix — survived
    the first version of this file, because the only thing watching the fallback
    was a source pin on its `return` line, and a return inside a branch nothing
    can enter is still there to be found. A presence pin cannot see reachability.
    """

    UNDATABLE = WEB

    def test_a_watched_transition_confirms_the_run(self):
        ok, url, why = research._chatgpt_landing_result(self.UNDATABLE, HOST)
        assert ok is True
        assert url == self.UNDATABLE
        assert why == "undatable_id_transition_observed"

    # ⛔ The other direction: nothing watched, nothing confirmed. Firing the
    # fallback here would bless a tab that never moved.
    def test_nothing_watched_means_the_send_did_not_land(self):
        ok, url, why = research._chatgpt_landing_result("", HOST)
        assert ok is False
        assert url == HOST
        assert why == "no_conversation_url"

    def test_the_failure_reports_the_last_url_we_saw(self):
        _ok, url, _why = research._chatgpt_landing_result("", "https://chatgpt.com/somewhere")
        assert url == "https://chatgpt.com/somewhere"

    # ⭐ The remembered conversation wins over the last observation — they can
    # differ when the tab moves again after the id we noted.
    def test_the_remembered_conversation_is_what_gets_confirmed(self):
        _ok, url, _why = research._chatgpt_landing_result(self.UNDATABLE, HOST)
        assert url == self.UNDATABLE and url != HOST


class TestTheSourceStillWiresItUp:
    """The loop is a closure inside an async function no test can drive, so these
    are source pins — deliberately narrow, and only for the wiring the pure tests
    above cannot reach."""

    SRC = (Path(__file__).resolve().parents[1] / "research.py").read_text(encoding="utf-8")

    def test_the_loop_delegates_to_the_pure_function(self):
        assert "_verdict = _chatgpt_landing_verdict(_last, _pre_send_url)" in self.SRC

    # ⚠ A PIN ON THE DELEGATION, NOT ON THE FALLBACK'S BODY. The previous version
    # asserted the fallback's `return` line was present in the file — and a mutant
    # that made the branch unenterable left that line exactly where it was and
    # survived. The behaviour now lives in `TestTheBudgetRunningOut`.
    def test_the_loop_delegates_its_tail_to_the_pure_function(self):
        assert "return _chatgpt_landing_result(_undatable, _last)" in self.SRC

    # ⭐ A fallback that confirms runs silently becomes the only check nobody
    # notices has taken over.
    def test_the_fallback_says_so_in_the_log(self):
        i = self.SRC.index('if _cg_why == "undatable_id_transition_observed":')
        window = self.SRC[i:i + 700]
        assert "no readable timestamp" in window
        assert '"WARN"' in window
