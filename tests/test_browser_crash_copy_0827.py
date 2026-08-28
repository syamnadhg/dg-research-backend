"""2026-08-27 — the crash notice promised a recovery that does not happen.

MEASURED, from the owner's log bundle (`6CB3MXQC`, run `chat_1787870237733_1`).
Gemini sat on the platform's "Writing your report…" for forty-seven minutes with
ZERO new output — 133 sites, 37 steps, `text_len 0` — while our CUA arbiter twice
looked at the page and ruled *"WORKING, not a frozen state"*. Then:

    [17:21:00] [WARN] [Gemini] Browser tab crashed — failing agent
    [17:21:04] [INFO] [Phase 2] Built 2 in-app primary links …
    [17:21:06] [INFO] PHASE 2 COMPLETE: 2/3 agents finished

What the person was told, from `emit_browser_recovery_status`:

    "Gemini tab crashed — auto-retrying from checkpoint…"
    "The pipeline will rebuild the browser session and resume."

⛔⛔ NOTHING WAS REBUILT AND NOTHING RESUMED. Six seconds later the phase reported
complete with two of three agents. All three callers of that notice `return
False` into exactly that path; the rebuild-and-resume sentence is true only when
the death takes the whole browser and an exception reaches `run_pipeline`, and
one sentence was covering both outcomes while naming the one that did not happen.

⛔ AND IT NEVER SAID WHERE THE FAILURE WAS. "Your browser tab crashed" reads as
the person's own machine, or as our pipeline. The research had been dead on the
platform's own page for the better part of an hour before the tab went.

⛔⛔ ALSO WORTH RECORDING: the `platform_crashed` copy added EARLIER THE SAME DAY
never fires for this case. `browser_crashed` calls no `fail_agent`, so nothing
persists "errored", `_needs_finalize` is false, and the exit sweep skips the
agent entirely — measured: run 2 logged **zero** "Auto-skip finalize" lines while
run 1's ChatGPT logged one. That fix improved a sentence nobody sees here.

▶ WHAT THIS COPY MAY CLAIM. Only what we observed: quiet for at least this long,
on the platform's page, re-checked this many times, then gone. NOT a cause. We
cannot separate a platform stall from our own scrapers going blind — that is the
false-positive class the arbiter exists for — and a dead tab looks identical
whether the platform hung, Chrome ran out of memory, or a profile lock was lost.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402


# The run-2 Gemini numbers, from the bundle.
GEMINI = dict(agent_label="Gemini", elapsed_sec=87 * 60, quiet_sec=53 * 60, rechecks=6)


def _copy(**kw):
    return research.browser_crash_copy(**kw)


class TestTheBrokenPromiseIsGone:
    """⛔⛔ The single most important property in this file."""

    def test_it_never_promises_a_retry(self):
        for kw in (GEMINI, dict(agent_label="Claude", elapsed_sec=600), dict()):
            title, details = _copy(**kw)
            blob = f"{title} {details}".lower()
            for lie in ("auto-retry", "auto-retrying", "will rebuild", "rebuild the browser",
                        "resume", "retrying", "from checkpoint"):
                assert lie not in blob, (lie, kw, blob)

    def test_it_says_what_actually_happened_instead(self):
        _t, d = _copy(**GEMINI)
        assert "the run continued without it" in d.lower()

    # ⛔ The old sentence called it "Browser tab crashed", which a person reads as
    # their own browser. Ours is a headless page on the platform's site.
    def test_it_does_not_blame_the_persons_browser(self):
        for kw in (GEMINI, dict(agent_label="Claude", elapsed_sec=600)):
            title, details = _copy(**kw)
            blob = f"{title} {details}".lower()
            assert "your browser" not in blob
            assert "browser tab crashed" not in blob

    def test_it_says_the_person_did_not_cause_it(self):
        _t, d = _copy(**GEMINI)
        assert "nothing on your side caused this" in d.lower()


class TestItPutsTheFailureOnThePlatformsPage:
    def test_a_named_agent_gets_its_own_page(self):
        _t, d = _copy(**GEMINI)
        assert "on its own page" in d

    # ⛔ With nobody to name there is no "own page" to point at, and saying it
    # anyway is noise — the first draft produced "The page on its own page".
    def test_an_unnamed_crash_does_not_claim_a_page_it_cannot_name(self):
        _t, d = _copy(elapsed_sec=300)
        assert "own page" not in d
        assert d.startswith("The page stopped responding after 5 minutes.")

    # ⛔⛔ THE COMBINATION MUTATION FOUND UNCOVERED. A whole-browser death that
    # ALSO went quiet takes the other branch entirely, and nothing was watching
    # it — so making `where` unconditional produced "It went quiet on its own
    # page" for a crash with no agent to attribute it to, and every test passed.
    def test_an_unnamed_crash_that_went_quiet_still_claims_no_page(self):
        _t, d = _copy(elapsed_sec=900, quiet_sec=600, rechecks=2)
        assert "own page" not in d, d
        assert "went quiet for at least 10 minutes" in d

    def test_the_title_names_the_agent(self):
        for name in ("Gemini", "ChatGPT", "Claude"):
            t, _d = _copy(agent_label=name, elapsed_sec=600)
            assert t == f"{name} stopped responding"
            for other in {"Gemini", "ChatGPT", "Claude"} - {name}:
                assert other not in t


class TestTheStallIsNamed:
    """The owner's requirement: say it got stuck and say we waited."""

    def test_the_silence_is_reported(self):
        _t, d = _copy(**GEMINI)
        assert "went quiet" in d
        assert "53 minutes" in d

    def test_the_wait_is_reported(self):
        _t, d = _copy(**GEMINI)
        assert "87 minutes" in d

    def test_the_rechecks_are_reported(self):
        _t, d = _copy(**GEMINI)
        assert "re-checked it 6 times" in d

    # ⛔⛔ "AT LEAST" IS LOAD-BEARING, NOT HEDGING. A WORKING verdict from the
    # arbiter rewinds the growth clock (up to `_ARBITER_MAX_WORKING_RESETS`
    # times), so the true silence can be LONGER than the number we hold — never
    # shorter. Stating it as exact would be the one direction that is a lie.
    def test_the_silence_is_stated_as_a_floor(self):
        _t, d = _copy(**GEMINI)
        assert "at least 53 minutes" in d

    def test_one_recheck_reads_as_english(self):
        _t, d = _copy(agent_label="ChatGPT", elapsed_sec=600, quiet_sec=300, rechecks=1)
        assert "re-checked it once" in d
        assert "1 time" not in d

    def test_no_rechecks_says_nothing_about_rechecks(self):
        _t, d = _copy(agent_label="Claude", elapsed_sec=900, quiet_sec=600, rechecks=0)
        assert "re-checked" not in d
        assert "went quiet" in d


class TestItOnlyClaimsWhatWeHold:
    """⛔ Every number in the sentence must come from a field we actually carry."""

    def test_a_death_with_no_stall_makes_no_stall_claim(self):
        _t, d = _copy(agent_label="Claude", elapsed_sec=12 * 60)
        assert "went quiet" not in d
        assert "at least" not in d
        assert d.startswith("Its own page stopped responding after 12 minutes.")

    def test_knowing_nothing_still_produces_a_true_sentence(self):
        t, d = _copy()
        assert t == "The browser stopped responding"
        assert d.startswith("The page stopped responding.")
        assert "minutes" not in d

    # ⛔ A zero or None clock is "we do not know", never "it took 0 minutes".
    def test_zero_and_none_are_treated_as_unknown(self):
        for bad in (0, None, -5):
            _t, d = _copy(agent_label="Gemini", elapsed_sec=bad, quiet_sec=bad)
            assert "0 minutes" not in d
            assert "minutes" not in d

    def test_booleans_are_not_mistaken_for_durations(self):
        # `True` is an int in Python and would render as "1 minutes".
        _t, d = _copy(agent_label="Gemini", elapsed_sec=True, quiet_sec=True)
        assert "minutes" not in d

    # ⭐ Sub-minute durations round UP to 1, never down to 0 — "stopped
    # responding after 0 minutes" is a sentence that reads as a bug report.
    def test_a_short_life_still_reads_as_at_least_a_minute(self):
        _t, d = _copy(agent_label="Gemini", elapsed_sec=20)
        assert "after 1 minutes" in d or "after 1 minute" in d
        assert "0 minutes" not in d

    # ⛔⛔ NEVER NAMES A CAUSE. We hold "our scrapers read nothing" and "our
    # arbiter said working" — neither separates a platform stall from our own
    # blindness, and a dead tab is identical whether the platform hung or Chrome
    # ran out of memory. See the module docstring.
    def test_it_does_not_diagnose_the_platform(self):
        _t, d = _copy(**GEMINI)
        low = d.lower()
        for guess in ("gemini's fault", "a bug in", "their side", "platform bug",
                      "google", "crashed", "out of memory", "a problem on"):
            assert guess not in low, guess


class TestTheEmitterPassesTheFactsThrough:
    """The clocks live on the pending entry and die with it, so the notice has to
    carry them out — nothing downstream can recover them."""

    SRC = (Path(__file__).resolve().parents[1] / "research.py").read_text(encoding="utf-8")

    def test_the_emitter_delegates_to_the_pure_builder(self):
        assert "_msg, _details = browser_crash_copy(" in self.SRC

    def test_the_crash_sweep_passes_the_clocks(self):
        i = self.SRC.index("emit_browser_recovery_status(\n                    2, agent=_crash_key,")
        window = self.SRC[i:i + 400]
        assert "elapsed_sec=_crash_elapsed" in window
        assert "quiet_sec=_crash_quiet" in window
        # ⛔ THE VALUE, NOT THE KEYWORD. `assert "rechecks=" in window` was the
        # first version, and a mutant that replaced the whole expression with
        # `rechecks=0` satisfied it — the sentence silently lost the clause that
        # says we did not give up early, with the suite green.
        assert 'rechecks=int(_crash_p.get("arbiter_working_resets", 0) or 0))' in window

    # ⛔⛔ `last_growth_time` DEFAULTS TO `start_time`, so a leg that never
    # produced anything at all would otherwise report its entire life as silence
    # — a true-sounding number about a thing that never started.
    def test_a_leg_that_never_grew_reports_no_silence(self):
        assert "_crash_grew = (_crash_p.get(\"last_growth_len\", 0) > 0" in self.SRC
        assert "if _crash_grew and _crash_p.get(\"last_growth_time\") else None" in self.SRC

    # ⛔ The notice is emitted BEFORE the results row is written, so reading the
    # elapsed from `results` would silently pass None.
    def test_the_elapsed_is_computed_not_read_from_results(self):
        assert "_crash_elapsed = int(time.time() - _crash_p.get(\"start_time\"" in self.SRC
