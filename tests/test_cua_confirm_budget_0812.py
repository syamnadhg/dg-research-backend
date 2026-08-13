"""Forty-four minutes spent asking a question that had already been answered.

WHAT HAPPENED (2026-08-12 e2e)

Phase 1's brief finished at t≈1014s. Phase 2 started 44 minutes later. In
between, `poll_until_done` made roughly forty visual-confirm calls, and the DOM
detector was RIGHT on every single one of the reads that triggered them.

THREE DEFECTS, COMPOUNDING.

  1. THE PROMPT COULD NOT BE ANSWERED. Completion was an AND: no stop button
     *and* the final paragraph of the response visible. The answer was in a
     canvas with the Activity panel open over it, so the final paragraph was
     not visible anywhere on screen — the completion branch was unsatisfiable
     no matter how finished the brief was. And with only two verdicts offered,
     "I cannot tell" had to be spelled as one of them, so the model said "still
     generating" while quoting "Worked for 16m 26s" back in the same answer.

  2. NOTHING BOUNDED THE DISAGREEMENT. A "still generating" answer reset the
     DOM streak to zero and re-armed the check, so the two sensors could argue
     forever at about a call a minute. Nothing else in the function could stop
     it: the stall surface lives in the OTHER arm of the same `if` and is
     unreachable once the DOM says done, `max_wait_min` is accepted and never
     referenced, and this call site — unlike its sibling at the activity-panel
     tier — had no timeout. One diagnosis ran 10.5 minutes.

  3. THE CONFIRM WAS ASKED AT ALL. The page was showing the thinking-time
     header the entire time. Vision exists to resolve DOM UNCERTAINTY; here the
     DOM was certain and correct, and the confirmation was a veto with no
     quorum.

WHAT THESE TESTS PIN

  ⭐ They RUN the loop. Every existing test of `poll_until_done` asserts against
  its source text, which is why a bug about control flow and termination lived
  in it: you cannot read a source string and learn whether something halts.

  1. The corroborator reads the real page, and length is NOT one.
  2. Corroborated → ZERO visual confirms. This is the whole cost fix.
  3. Uncorroborated → the confirm happens, and terminates, in all four cells of
     (DOM right/wrong × vision right/wrong).
  4. ⛔ Budget exhausted with a Stop button named EVERY time is the one case
     vision exists for — ChatGPT renames its stop markup, the DOM goes blind,
     and vision is the only honest sensor. That must reach a user decision, and
     must never silently extract.
  5. "Recognised nothing" is never logged as "observed generation".
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from _domshim import el, run_js  # noqa: E402

LIVE_BADGE = "Worked for 16m 26s"

# The verbatim shape of the read the vision model returned at 10:07, while
# answering "still generating".
LIVE_READ = (
    "Looking at the screen: there is no filled square stop button in the "
    "composer. I can see a \"Worked for 16m 26s\" label at the top of the "
    "response, and the Activity panel is open on the right.")


# ══════════════════════════════════════════════════════════════════════════
# A. the corroborator, against a real DOM
# ══════════════════════════════════════════════════════════════════════════

class _ShimPage:
    """A page whose `evaluate` runs the real JS against a real DOM spec."""

    def __init__(self, spec, url="https://chatgpt.com/c/abc", frames=()):
        self.spec = spec
        self.url = url
        self.main_frame = self
        self._frames = [self, *frames]
        self.calls = []

    @property
    def frames(self):
        return self._frames

    def is_closed(self):
        return False

    async def evaluate(self, js, arg=None):
        self.calls.append(js)
        return run_js(self.spec, js, arg)["ret"]


def _page_showing(text, **kw):
    return _ShimPage(el("body", kids=[el("main", kids=[el("div", text=text)])]), **kw)


def test_the_badge_on_the_page_is_read_back_verbatim():
    """Returns WHAT it matched, not a bool. A log line that quotes the label is
    what makes the next vendor rename visible instead of silent.

    The match ends at the first unit ("worked for 16m" out of "Worked for 16m
    26s") because the pattern's job is to identify the header, not to parse the
    duration. What matters is that the log carries enough to recognise it."""
    page = _page_showing(f"{LIVE_BADGE}\nThe finished brief follows.")
    assert asyncio.run(research._chatgpt_done_badge(page)) == "worked for 16m"


def test_a_page_with_no_badge_corroborates_nothing():
    page = _page_showing("A response with no time badge anywhere in it.")
    assert asyncio.run(research._chatgpt_done_badge(page)) == ""


def test_report_prose_never_corroborates():
    """⛔ The false-complete guard at the corroborator. A brief writes "worked
    for 3 years" as an ordinary sentence; if that skipped the visual confirm,
    the fix would have replaced a slow run with a wrong one."""
    page = _page_showing("The founders worked for 3 years before the Series A.")
    assert asyncio.run(research._chatgpt_done_badge(page)) == ""


def test_length_alone_is_never_a_corroborator():
    """⭐ The build plan proposed `last_seen_len >= 2000` as an alternative
    corroborator, and it is unsound in exactly the case the confirm exists for.

    If ChatGPT renames its stop-button markup, the DOM detector goes blind and
    reports "not generating" MID-STREAM — at which point there is plenty of
    text. A length corroborator would skip the confirm and extract an in-flight
    brief: the #753 false-complete, reintroduced through the front door.

    Length says a response is BIG. Only the header says it is DONE."""
    page = _page_showing("x" * 60000)
    assert asyncio.run(research._chatgpt_done_badge(page)) == ""


def test_the_badge_is_found_inside_a_deep_research_frame():
    """The answer sometimes renders in the sandbox frame. The host walk covers
    it for the same reason the completion detector's does."""
    frame = _ShimPage(
        el("body", kids=[el("div", text=f"{LIVE_BADGE} — report body")]),
        url="https://connector-openai-deep-research.web-sandbox.oaiusercontent.com/?app=x")
    page = _ShimPage(el("body", kids=[el("div", text="host shell, nothing here")]),
                     frames=[frame])
    assert asyncio.run(research._chatgpt_done_badge(page)) == "worked for 16m"


def test_a_page_that_cannot_be_read_corroborates_nothing():
    """Fails toward ASKING, never toward assuming. An unreadable page is the
    definition of DOM uncertainty, which is when vision is supposed to run."""

    class _Dead(_ShimPage):
        async def evaluate(self, js, arg=None):
            raise RuntimeError("target closed")

    page = _Dead(el("body"))
    assert asyncio.run(research._chatgpt_done_badge(page)) == ""


# ══════════════════════════════════════════════════════════════════════════
# B. the harness that RUNS poll_until_done
# ══════════════════════════════════════════════════════════════════════════

class _Browser:
    def __init__(self, page):
        self.page = page
        self.switches = 0

    async def switch_to_page(self, page):
        self.switches += 1


class _LoopPage:
    """A page for the loop itself. `evaluate` answers the scroll payload and the
    badge probe; nothing else in the verify-False path evaluates anything.

    The badge answer is scripted rather than shimmed on purpose — section A
    above pins the probe against a real DOM, and these tests are about what the
    LOOP does with each answer. Splitting them means a mutation that breaks the
    probe and one that breaks the loop are killed by different tests."""

    def __init__(self, url="https://chatgpt.com/c/abc"):
        self.url = url
        self.main_frame = self
        self.frames = [self]

    def is_closed(self):
        return False

    async def evaluate(self, js, arg=None):
        # `_page_is_dead` probes for a live document before anything downstream
        # is allowed to read "not generating" as "done". Answering it honestly
        # matters: a fake that returned None here would make every test below
        # pass through the dead-page branch instead of the one under test.
        if "document.body" in js and "scrollTo" not in js:
            return True
        return None


class Harness:
    """Runs the real `poll_until_done` with everything external scripted.

    What is REAL: the loop, the corroborator gate, the budget, the polarity
    rules, the verdict parser, the backoff arithmetic, the exception.
    What is scripted: the DOM verdicts, the vision answers, and the clock."""

    def __init__(self, monkeypatch, *, dom, vision, badge="",
                 label="Phase1-followup", phase=1):
        self.dom = list(dom)               # verify_fn answers, in order
        self.vision = list(vision)         # what agent_loop returns, in order
        self.badge = badge
        self.label = label
        self.phase = phase
        self.dom_reads = 0
        self.confirms = 0
        self.fixes = 0
        self.missions = []                 # every mission string agent_loop saw
        self.sleeps = []
        self.wait_for_timeouts = []
        self.logs = []
        self._mp = monkeypatch
        self._install()

    # ── the scripted DOM ──
    async def verify_fn(self, page):
        self.dom_reads += 1
        return self.dom[min(self.dom_reads, len(self.dom)) - 1]

    def _install(self):
        mp = self._mp

        async def _badge(page):
            return self.badge
        mp.setattr(research, "_chatgpt_done_badge", _badge)

        async def _agent_loop(client, browser, prompt, mission, **kw):
            self.missions.append(mission)
            if mission == research.PROMPT_FIX_ISSUE or "needs clicking" in mission:
                self.fixes += 1
                return {"status": "done", "text": "clicked"}
            self.confirms += 1
            nxt = self.vision[min(self.confirms, len(self.vision)) - 1]
            if isinstance(nxt, BaseException):
                raise nxt
            return nxt
        mp.setattr(research, "agent_loop", _agent_loop)

        async def _shadow(page, *, cua_coro_factory=None, **kw):
            # Calls the factory for real, so the timeout wrapper, the mission
            # text and the error handling are all exercised rather than mocked
            # away. This is the layer the production code actually awaits.
            return await cua_coro_factory()
        mp.setattr(research, "_shadow_observed_cua", _shadow)

        _real_wait_for = asyncio.wait_for

        async def _wait_for(aw, timeout=None):
            self.wait_for_timeouts.append(timeout)
            return await _real_wait_for(aw, timeout)
        mp.setattr(research.asyncio, "wait_for", _wait_for)

        async def _sleep(secs, *a, **k):
            self.sleeps.append(secs)
        mp.setattr(research.asyncio, "sleep", _sleep)

        mp.setattr(research, "log", lambda msg, level="INFO": self.logs.append(str(msg)))
        mp.setattr(research, "emit_event", lambda *a, **k: None)
        # No scrape for this label, and none wanted: `last_seen_len` and the
        # stall window belong to the OTHER arm of the loop.
        mp.setattr(research, "SCRAPE_FNS", {})

    def run(self, *, poll_interval=30):
        page = _LoopPage()
        return asyncio.run(research.poll_until_done(
            page, self.verify_fn, self.label, poll_interval, 45,
            browser=_Browser(page), cua_client=object(), phase=self.phase))

    @property
    def log_text(self):
        return "\n".join(self.logs)


def _says(text):
    return {"status": "done", "text": text}


GENERATING = _says("still generating — there is a filled square Stop button in the composer")
GENERATING_NO_STOP = _says("still generating — a 'Finalizing answer' status is showing")
COMPLETE = _says("response complete — a finished document card and a sources list")
CANNOT_TELL = _says("cannot determine — the Activity panel covers the response entirely")
STOP_AFFIRMED = _says("Stop button: Yes. The composer shows a filled square.")


# ══════════════════════════════════════════════════════════════════════════
# C. corroborated → zero confirms
# ══════════════════════════════════════════════════════════════════════════

def test_a_corroborated_completion_spends_no_visual_confirm(monkeypatch):
    """⭐ THE COST FIX. This is the 2026-08-12 run: the page was showing the
    header the whole time. Forty calls become zero."""
    h = Harness(monkeypatch, dom=[False], vision=[GENERATING], badge=LIVE_BADGE)
    assert h.run() is True
    assert h.confirms == 0, "a visual confirm was spent on a page that already said done"


def test_the_log_quotes_what_corroborated_it(monkeypatch):
    """A line naming the label is what makes the next rename visible."""
    h = Harness(monkeypatch, dom=[False], vision=[GENERATING], badge=LIVE_BADGE)
    h.run()
    assert LIVE_BADGE in h.log_text
    assert "no visual confirm needed" in h.log_text


def test_without_a_corroborator_the_confirm_still_happens(monkeypatch):
    """The negative control for every test above. If this stops firing, the
    corroborator has become 'always true' and the fix is just 'never ask'."""
    h = Harness(monkeypatch, dom=[False], vision=[COMPLETE], badge="")
    assert h.run() is True
    assert h.confirms == 1


def test_the_dom_must_still_agree_after_a_corroborated_skip(monkeypatch):
    """Skipping the confirm does NOT skip the re-verify. A page that flips back
    to generating on the 3-second double-check keeps polling."""
    h = Harness(monkeypatch, dom=[False, False, True, False, False, False],
                vision=[COMPLETE], badge=LIVE_BADGE)
    assert h.run() is True
    assert h.confirms == 0
    assert h.dom_reads > 3, "the re-verify was skipped along with the confirm"


# ══════════════════════════════════════════════════════════════════════════
# D. uncorroborated → bounded, and terminating in all four cells
# ══════════════════════════════════════════════════════════════════════════

def test_a_vision_complete_ends_the_poll(monkeypatch):
    h = Harness(monkeypatch, dom=[False], vision=[COMPLETE])
    assert h.run() is True
    assert h.confirms == 1
    assert "agrees the response is complete" in h.log_text


def test_cannot_determine_does_not_veto(monkeypatch):
    """⭐ Where the two twins deliberately diverge. In the safety net the DOM
    says GENERATING, so an unreadable screen leaves a live contradiction and
    waiting is the only safe reading. Here the DOM says FINISHED and nothing
    contradicts it — "I recognised nothing" is not evidence against a decision
    already made correctly, and treating it as a veto is what cost 44 minutes."""
    h = Harness(monkeypatch, dom=[False], vision=[CANNOT_TELL])
    assert h.run() is True
    assert h.confirms == 1


def test_recognising_nothing_is_never_logged_as_observing_generation(monkeypatch):
    """The #753 lesson, applied to this twin. For two months the log asserted a
    positive observation where the truth was "I matched no rule", and that
    wording is what hid a vendor relabel for forty minutes."""
    h = Harness(monkeypatch, dom=[False], vision=[CANNOT_TELL])
    h.run()
    assert "recognised nothing conclusive" in h.log_text
    assert "reports generation" not in h.log_text


def test_the_live_2026_08_12_read_no_longer_blocks_the_phase(monkeypatch):
    """The verbatim vision answer from 10:07, fed through the real parser. Under
    the old inline parse this was "still generating" forty times over."""
    h = Harness(monkeypatch, dom=[False], vision=[_says(LIVE_READ)])
    assert h.run() is True
    assert h.confirms == 1


def test_a_persistent_disagreement_terminates_with_the_dom_winning(monkeypatch):
    """⭐ TERMINATION. Vision says generating on every read and never names a
    Stop button. The budget runs out and the DOM — which has been right all
    along — decides. Previously this looped until a human pressed a button."""
    h = Harness(monkeypatch, dom=[False], vision=[GENERATING_NO_STOP] * 9)
    assert h.run() is True
    assert h.confirms == 3, f"budget was not 3: {h.confirms}"
    assert "without once naming a Stop button" in h.log_text


def test_the_disagreement_backs_off_further_each_time(monkeypatch):
    """Escalating waits, so a genuinely slow finish is still caught without
    paying for a tight loop. Order matters: a flat backoff would make the
    argument cheap rather than short."""
    h = Harness(monkeypatch, dom=[False], vision=[GENERATING_NO_STOP] * 9)
    h.run()
    long_sleeps = [s for s in h.sleeps if s >= 60]
    assert long_sleeps == [60, 120, 240], long_sleeps


def test_three_stop_button_sightings_reach_a_user_decision(monkeypatch):
    """⛔ THE CASE VISION EXISTS FOR. ChatGPT renames its stop-button markup,
    the DOM detector goes blind and reports "finished" mid-stream, and the
    visual check is the only sensor still telling the truth.

    A bare call-cap would silently extract an in-flight brief here. Polarity is
    what makes the budget safe: a confirm that POSITIVELY affirmed a Stop button
    every time is not overruled — it is a real sensor conflict, and the honest
    move is to stop and ask."""
    h = Harness(monkeypatch, dom=[False], vision=[STOP_AFFIRMED] * 9)
    with pytest.raises(research._BriefStreamStalled) as exc:
        h.run()
    assert exc.value.contested is True
    assert h.confirms == 3


def test_a_stop_button_seen_only_sometimes_does_not_contest(monkeypatch):
    """The threshold is real, not decorative. Two sightings out of three is an
    inconsistent read, not a sensor conflict — and an inconsistent read is
    exactly what #755 records the vision model doing on an IDENTICAL screen
    ("still generating" at 09:00 and 09:05, "complete" at 09:10)."""
    h = Harness(monkeypatch, dom=[False],
                vision=[STOP_AFFIRMED, GENERATING_NO_STOP, STOP_AFFIRMED] * 3)
    assert h.run() is True
    assert h.confirms == 3


def test_a_dead_vision_call_cannot_keep_the_loop_alive(monkeypatch):
    """A confirm that errors is not a verdict, so it is not parsed — but it DID
    consume budget. The old code's `cua_checked = False; continue` had no
    counter at all, so a vision endpoint returning 529 every tick kept the poll
    alive forever with no evidence on either side."""
    h = Harness(monkeypatch, dom=[False],
                vision=[{"status": "error", "text": "529 overloaded"}] * 9)
    assert h.run() is True
    assert h.confirms == 3
    assert "visual confirm unavailable" in h.log_text


def test_an_exhausted_agent_loop_is_treated_as_no_verdict(monkeypatch):
    """`max_iterations` returns the LAST text block, possibly mid-reasoning
    rather than a conclusion — the same guard the safety-net twin carries."""
    h = Harness(monkeypatch, dom=[False],
                vision=[{"status": "max_iterations",
                         "text": "...I should check whether it is complete"}] * 9)
    assert h.run() is True
    assert h.confirms == 3


def test_the_confirm_call_is_wrapped_at_two_minutes(monkeypatch):
    """⛔ The sibling at the activity-panel tier has wrapped at 120s since
    2026-07; this call never did, and one diagnosis ran 10.5 minutes inside a
    loop with no other ceiling."""
    h = Harness(monkeypatch, dom=[False], vision=[COMPLETE])
    h.run()
    assert 120.0 in h.wait_for_timeouts, h.wait_for_timeouts


def test_a_timed_out_confirm_is_unavailable_not_a_verdict(monkeypatch):
    h = Harness(monkeypatch, dom=[False], vision=[asyncio.TimeoutError()] * 9)
    assert h.run() is True
    assert h.confirms == 3
    assert "visual confirm unavailable" in h.log_text


def test_the_budget_survives_the_dom_flipping_back_to_generating(monkeypatch):
    """⛔ The budget is a property of the whole poll, not of a streak.

    The 44 minutes accumulated precisely because a veto reset the DOM streak to
    zero — so the argument restarted, indefinitely, and no counter anywhere
    recorded that it had happened before. A page that oscillates must not be
    able to buy more confirms by oscillating."""
    # generating / not-generating, alternating, for a long time
    h = Harness(monkeypatch, dom=[False, False, True, False, False, True] * 20,
                vision=[GENERATING_NO_STOP] * 20)
    assert h.run() is True
    assert h.confirms == 3, f"an oscillating page bought {h.confirms} confirms"


def test_a_badge_that_appears_late_ends_the_argument(monkeypatch):
    """The corroborator is re-read every tick, not once. A brief that renders
    its header a poll or two after the DOM first reports finished stops the
    argument at that moment instead of spending the rest of the budget."""
    h = Harness(monkeypatch, dom=[False], vision=[GENERATING_NO_STOP] * 9)

    real_confirms = []

    async def _badge_appears(page):
        # nothing to corroborate until one confirm has already disagreed
        real_confirms.append(h.confirms)
        return LIVE_BADGE if h.confirms >= 1 else ""
    monkeypatch.setattr(research, "_chatgpt_done_badge", _badge_appears)

    assert h.run() is True
    assert h.confirms == 1, f"kept arguing after the page said done: {h.confirms}"


def test_a_poll_with_no_vision_client_still_completes(monkeypatch):
    """`poll_until_done` is also called without a browser/CUA client. The budget
    and the contested raise must be unreachable there, not merely unused — a
    contested card raised on a run that never made a visual confirm would be a
    card about evidence that does not exist."""
    h = Harness(monkeypatch, dom=[False], vision=[COMPLETE])
    page = _LoopPage()
    assert asyncio.run(research.poll_until_done(
        page, h.verify_fn, "Phase1-followup", 30, 45,
        browser=None, cua_client=None, phase=1)) is True
    assert h.confirms == 0


def test_a_needs_click_verdict_still_tries_to_unblock_the_page(monkeypatch):
    """Preserved behaviour: a diagnosis that names a blocking button gets one
    attempt to press it, and a short wait rather than the backoff — the page
    was just changed, so the next read is about the click's effect."""
    h = Harness(monkeypatch, dom=[False],
                vision=[_says("needs click — an 'Answer now' button is blocking"),
                        COMPLETE])
    assert h.run() is True
    assert h.fixes == 1
    assert 5 in h.sleeps


# ══════════════════════════════════════════════════════════════════════════
# E. the mission the model is actually given
# ══════════════════════════════════════════════════════════════════════════

def _mission(monkeypatch):
    h = Harness(monkeypatch, dom=[False], vision=[COMPLETE])
    h.run()
    return h.missions[0]


def test_completion_is_a_disjunction_not_an_and(monkeypatch):
    """⭐ The prompt defect that started it. The old mission made completion
    conditional on the final paragraph being visible, which in a canvas layout
    with the Activity panel open is unsatisfiable regardless of the truth."""
    m = _mission(monkeypatch)
    assert "final paragraph of the response is visible" not in m
    assert "any ONE of these is enough" in m


def test_the_mission_offers_a_third_answer(monkeypatch):
    """With two verdicts, "I cannot tell" has to be spelled as one of them —
    and the safer-sounding one is "still generating", so a failure to READ came
    back as a positive observation of generation."""
    m = _mission(monkeypatch)
    assert "cannot determine" in m
    assert "valid and useful answer" in m


def test_the_mission_names_the_current_time_badge(monkeypatch):
    """Both spellings. Naming only the old one is the rot this wave started as."""
    m = _mission(monkeypatch)
    assert "Worked for" in m
    assert "Thought for" in m


def test_the_mission_forbids_clicking(monkeypatch):
    """This inspector must never touch the Stop button it is looking for."""
    assert "do not click" in _mission(monkeypatch).lower()


def test_generation_still_overrides_everything(monkeypatch):
    """The cost asymmetry is unchanged: a positively observed working indicator
    wins over any completion trace on the same screen."""
    h = Harness(monkeypatch, dom=[False],
                vision=[_says("There is a document card AND a filled square Stop "
                              "button in the composer — still generating")] * 9)
    assert h.run() is True          # terminates
    assert h.confirms == 3          # but it argued the whole way, never agreeing
    assert "agrees the response is complete" not in h.log_text


# ══════════════════════════════════════════════════════════════════════════
# F. the card the contested case produces
# ══════════════════════════════════════════════════════════════════════════

def test_a_contested_card_does_not_claim_the_page_stopped():
    """⛔ The copy must not assert something we specifically know may be false.
    If the visual check is the one telling the truth, the page never stopped."""
    title, body = research._p1_stall_card_copy(
        contested=True, salvageable=True, text_len=62492)
    assert "stopped updating" not in body
    assert "stopped responding" not in title.lower()
    assert "disagree" in body


def test_a_genuinely_stalled_card_keeps_its_original_words():
    title, body = research._p1_stall_card_copy(
        contested=False, salvageable=True, text_len=62492)
    assert title == "ChatGPT stopped responding"
    assert "stopped updating while writing the brief" in body


@pytest.mark.parametrize("contested", [True, False])
def test_the_character_count_only_appears_when_it_can_be_used(contested):
    """The salvage action extracts whatever streamed, so quoting a count next to
    an offer that isn't there is the 2026-08-11 "Skip" defect again."""
    _t, body = research._p1_stall_card_copy(
        contested=contested, salvageable=False, text_len=180)
    assert "180" not in body
    assert "cannot continue without a brief" in body


@pytest.mark.parametrize("contested", [True, False])
def test_the_salvageable_card_quotes_the_count(contested):
    _t, body = research._p1_stall_card_copy(
        contested=contested, salvageable=True, text_len=62492)
    assert "62,492" in body


def test_the_exception_defaults_to_the_stall_reading():
    """`contested` defaults False, so the 20-minute multi-signal stall — which
    raises this exception without naming it — keeps the copy it always had."""
    exc = research._BriefStreamStalled("flat for 1200s", text_len=500)
    assert exc.contested is False
    assert exc.text_len == 500
