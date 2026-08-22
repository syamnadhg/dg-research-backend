"""Wave 3b: three Claude source gates that failed silently, and one that could not fire.

Measured on this machine's own logs, 2026-08-22 (`~/.super-research/logs`):

  * `layer=dom, walker_root=geo, panel_open=True` × **119**
  * `layer=dom, walker_root=none, panel_open=False` × **28**
  * `artifact panel opened` **23** vs `didn't stick` **28** — the panel fails to
    stick MORE often than it opens.
  * `[Claude] vision-urls extracted` fired **3** times ever, against ChatGPT's
    **9** — because Claude's rescue was gated on the panel being open, i.e. on
    the very condition it exists to rescue.
  * `Artifact tracking: 1 URLs` × **74 of 78**.

Three defects follow from that, and each one is a distinct shape:

  1. `artifact_count == 0 → return None` was completely silent, so a wrong zero
     and a genuine zero were byte-identical at the earliest gate in the path.
  2. The DOM-miss reset sat OUTSIDE the source-url check, so a checklist with
     steps and no citations cleared the counter that arms the CUA escalation
     written for exactly that case — every cycle, forever.
  3. The vision rescue's gate WAS the condition it rescues.

⚠ And a fourth, caught while fixing the third: the first version of the new
rescue arm covered ChatGPT by reading three `p` keys that do not exist, so it
would have concluded "opener still trying" forever — a guard that cannot fire,
added while fixing a guard that could not fire. The arm is Claude-only, and
`test_the_predicate_only_reads_keys_that_exist` is why.
"""

from __future__ import annotations

import importlib
import inspect

from conftest import code_only_deep

research = importlib.import_module("research")

RESCUE = research.vision_url_rescue_should_run
FLOOR = research._VISION_URL_CLOSED_PANEL_MIN_S
LAST_MISS = research._PANEL_CUA_RETRY_AT_MISSES[-1]


def _rescue(**kw):
    base = {"agent": "Claude", "panel_open": False, "elapsed_sec": FLOOR + 1,
            "dom_source_count": 0, "open_attempts_burned": 3,
            "dom_misses": 0, "ever_opened": False}
    base.update(kw)
    return RESCUE(**base)


# ── the three original arms must be unchanged ────────────────────────────────

class TestTheOriginalArmsStillWork:
    def test_an_open_claude_panel_still_runs_the_rescue(self):
        ok, why = _rescue(panel_open=True, open_attempts_burned=0)
        assert ok is True and why == "panel-open"

    def test_an_open_chatgpt_panel_still_runs_the_rescue(self):
        ok, why = _rescue(agent="ChatGPT", panel_open=True)
        assert ok is True and why == "panel-open"

    def test_gemini_still_runs_on_elapsed_alone(self):
        assert _rescue(agent="Gemini", elapsed_sec=121)[0] is True
        assert _rescue(agent="Gemini", elapsed_sec=120)[0] is False

    def test_gemini_has_no_never_opened_arm(self):
        """Gemini's arm is elapsed-only by design; it must not fall through into
        the Claude branch and gain a second way to fire."""
        ok, why = _rescue(agent="Gemini", elapsed_sec=10)
        assert ok is False and why == "no-arm"

    def test_an_unknown_agent_gets_nothing(self):
        ok, why = _rescue(agent="NotebookLM", panel_open=True)
        assert ok is False and why == "no-arm"


# ── the new arm: the panel that never opened ─────────────────────────────────

class TestTheNeverOpenedArm:
    def test_a_never_opened_panel_out_of_road_now_gets_the_rescue(self):
        """⛔ THE WHOLE POINT. Before this, `not panel_open` was a hard refusal —
        so the 28-of-147 reads where no panel ever mounted were denied the only
        fallback they had left."""
        ok, why = _rescue()
        assert ok is True
        assert "panel-never-opened" in why
        assert "dom_sources=0" in why, "the reason must carry its evidence"

    def test_dom_misses_past_the_last_threshold_also_count_as_out_of_road(self):
        ok, _ = _rescue(open_attempts_burned=0, dom_misses=LAST_MISS)
        assert ok is True

    def test_an_opener_still_trying_is_refused(self):
        """⛔ WITHOUT THIS THE FIX IS WORSE THAN THE BUG. The caller sets
        `vision_urls_done` on both paths, so a rescue that burns its single shot
        on an early blank frame means a panel that opens later never gets
        rescued at all."""
        ok, why = _rescue(open_attempts_burned=2, dom_misses=LAST_MISS - 1)
        assert ok is False and why == "opener-still-trying"

    def test_a_panel_that_opened_earlier_is_refused(self):
        """It had its chance and took the panel-open arm; a second entitlement
        would double the cost on a healthy run."""
        ok, why = _rescue(ever_opened=True)
        assert ok is False and why == "panel-opened-earlier"

    def test_a_run_that_already_has_sources_is_refused(self):
        """This is what bounds the cost to the failing runs only."""
        ok, why = _rescue(dom_source_count=1)
        assert ok is False and why == "dom-has-sources"

    def test_too_early_is_refused_at_the_boundary(self):
        """The floor is a minimum, so AT the floor the rescue is allowed."""
        assert _rescue(elapsed_sec=FLOOR - 1)[1] == "too-early"
        assert _rescue(elapsed_sec=FLOOR)[0] is True
        assert _rescue(elapsed_sec=0)[1] == "too-early"

    def test_chatgpt_gets_no_never_opened_arm(self):
        """⚠ A DECISION, not an omission. The first version of this arm read
        `chatgpt_panel_reopens`, `chatgpt_activity_dom_misses` and
        `_chatgpt_panel_ever_open` — none of which exist — so it would have read
        "opener still trying" forever. ChatGPT's rescue already succeeds three
        times as often and nothing about its never-opened case is measured."""
        ok, why = _rescue(agent="ChatGPT")
        assert ok is False and why == "no-arm"

    def test_the_predicate_only_reads_keys_that_exist(self):
        """The call site must pass poll-state keys the poll loop actually writes.
        An invented key reads absent, which silently pins the arm shut — the
        exact defect this wave exists to remove, reintroduced by the fix.

        Source-pinned because nothing in the suite executes
        `poll_all_agents_round_robin`."""
        src = inspect.getsource(research.poll_all_agents_round_robin)
        call = src[src.index("vision_url_rescue_should_run("):]
        call = call[:call.index("\n                )")]
        # ⛔ code_only_deep, not raw source. The docstrings BELOW and in the
        # predicate itself name the invented keys in order to explain why they
        # are wrong — and a presence assertion cannot tell code from prose. This
        # repo has had a mutation survive on exactly that.
        whole = code_only_deep(inspect.getsource(research))
        for key in ("claude_panel_reopens", "claude_artifact_dom_misses",
                    "_claude_panel_ever_open"):
            assert f'"{key}"' in call, f"the call must read {key}"
            # Written elsewhere in the module, not only read here.
            assert whole.count(f'"{key}"') >= 2, (
                f"{key} is read by the rescue gate but never written — an "
                f"invented key would pin the arm shut"
            )
        for invented in ("chatgpt_panel_reopens", "chatgpt_activity_dom_misses",
                         "_chatgpt_panel_ever_open"):
            assert invented not in whole, (
                f"{invented} does not exist in the poll state; reading it would "
                f"make the arm unable to fire"
            )


# ── the run-level verdict, which is where the WARN went ──────────────────────

class TestRunVerdict:
    def _v(self, **kw):
        base = {"url_count": 0, "observed_count": 0, "panel_ever_opened": False,
                "toggle_outcome": "absent"}
        base.update(kw)
        return research.claude_sources_run_verdict(**base)

    def test_sources_in_hand_is_info(self):
        msg, lvl = self._v(url_count=44, observed_count=44)
        assert lvl == "INFO" and "44 source urls" in msg

    def test_a_count_without_the_sources_is_warn(self):
        """The measured gap: Claude says 553 and we captured none of them."""
        msg, lvl = self._v(url_count=0, observed_count=553)
        assert lvl == "WARN"
        assert "553" in msg and "the count is ours, the sources are not" in msg

    def test_claude_own_zero_is_info_not_warn(self):
        """⭐ THIS is why the disclosure is worth pressing at all: it is the only
        surface that can say a zero is an ANSWER. Without it every zero looked
        the same, and 13 of 22 finished runs ended in one."""
        msg, lvl = self._v(url_count=0, observed_count=0, toggle_outcome="disabled")
        assert lvl == "INFO"
        assert "an empty result, not a failed read" in msg

    def test_zero_from_everything_with_no_answer_anywhere_is_warn(self):
        msg, lvl = self._v(url_count=0, observed_count=0, toggle_outcome="absent")
        assert lvl == "WARN"
        assert "indistinguishable" in msg

    def test_a_failed_press_does_not_get_claude_benefit_of_the_doubt(self):
        """`press_failed` is not `disabled`. Treating them alike would let our
        own failure be reported as Claude having no sources."""
        assert self._v(toggle_outcome="press_failed")[1] == "WARN"
        assert self._v(toggle_outcome="read_failed")[1] == "WARN"
        assert self._v(toggle_outcome=None)[1] == "WARN"

    def test_the_line_always_records_whether_the_panel_ever_opened(self):
        for opened in (True, False):
            msg, _ = self._v(url_count=1, panel_ever_opened=opened)
            assert f"panel_ever_opened={opened}" in msg

    def test_it_is_wired_into_the_finished_read(self):
        src = inspect.getsource(research.claude_finished_sources_read)
        assert "claude_sources_run_verdict(" in src
        # It must judge the MERGED numbers, or it reports the state before the
        # panel read it is summarising.
        assert src.index("merge_claude_sources(") < src.index(
            "claude_sources_run_verdict("), (
            "the verdict must come after the merge, or it judges stale counts"
        )


# ── the two silent gates in the tracking path ────────────────────────────────

class TestSilentGatesNowSpeak:
    def test_a_zero_card_count_no_longer_returns_in_silence(self):
        """The earliest gate in the Claude tracking path, and it logged nothing —
        so a wrong zero (selectors matched nothing on a page that has a card) was
        byte-identical to a genuine zero. 28 of 147 reads ended here."""
        src = inspect.getsource(research.scrape_claude_artifact_tracking)
        head = src[:src.index("content = \"\"")]
        assert "if artifact_count == 0:" in head
        assert "log(" in head, "the zero-count return must say so"
        assert "card count read 0" in head

    def test_the_dom_miss_reset_is_inside_the_source_url_check(self):
        """⛔⛔ It used to sit one level out, so ANY returned data — a checklist
        with steps and sections and not one citation — cleared the counter that
        is the sole input to `panel_cua_should_escalate`. The escalation written
        for exactly that case was disarmed by the case itself, every cycle.

        Measured shape: 74 of 78 reads returned exactly one url.

        Pinned by INDENTATION rather than presence, because presence is what the
        bug also satisfied."""
        src = inspect.getsource(research.poll_all_agents_round_robin)
        reset = 'p["claude_artifact_dom_misses"] = 0'
        assert src.count(reset) == 1
        line = next(ln for ln in src.splitlines() if reset in ln)
        reset_indent = len(line) - len(line.lstrip())
        guard = next(ln for ln in src.splitlines()
                     if 'if artifact_data.get("source_urls"):' in ln)
        guard_indent = len(guard) - len(guard.lstrip())
        assert reset_indent > guard_indent, (
            "the reset must be INSIDE the source-url check — outside it, a "
            "checklist with no citations counts as a successful read"
        )

    def _source_less_branch(self):
        """The `else` arm of `if artifact_data.get("source_urls"):`, comments and
        docstrings blanked.

        ⛔ Sliced from the branch OPENER, not from the log text. Mutation caught
        both mistakes: slicing from the message meant a line inserted ABOVE it
        was outside the block, and asserting the message text was satisfied by a
        mutant that kept the f-string and dropped the `log(` call around it.
        """
        src = code_only_deep(research.poll_all_agents_round_robin)
        head = src.index('if artifact_data.get("source_urls"):')
        # The matching else is at the same indentation as that if.
        line = src[:head].rsplit("\n", 1)[-1]
        indent = len(line)
        marker = "\n" + " " * indent + "else:\n"
        rest = src[head:]
        blk = rest[rest.index(marker) + len(marker):]
        # ends at the next line indented less than the branch body
        out = []
        for ln in blk.splitlines():
            if ln.strip() and (len(ln) - len(ln.lstrip())) <= indent:
                break
            out.append(ln)
        return "\n".join(out)

    def test_a_source_less_panel_read_is_logged(self):
        """The normal case in the corpus — 74 of 78 reads — and it logged nothing
        at all. Asserted as a `log(` CALL, because the message text alone is
        satisfied by a mutant that keeps the string and drops the call."""
        blk = self._source_less_branch()
        assert "log(" in blk, "the source-less read must actually be logged"
        assert "returned no source " in blk
        assert '"INFO"' in blk, "an expected outcome is INFO, not WARN"

    def test_the_source_less_branch_does_not_bump_the_open_failure_counter(self):
        """⚠ Deliberate: that counter drives the CUA tier-3, whose job is to OPEN
        the panel — and on this branch the panel is open. Bumping it would send a
        visual click at a panel that is already there."""
        blk = self._source_less_branch()
        assert 'claude_artifact_dom_misses"]' not in blk
