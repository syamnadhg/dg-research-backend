"""The two halves of ChatGPT's shimmer were split apart and never recombined.

THE REPORT (owner, watching a live run 2026-08-19 19:10–19:23): ChatGPT's
shimmering P1 line "is only clickable at times — like when it says stuff like
'Searched n websites'".

WHAT THE PHASE DID: twenty-three panel misses in 12m47s, all three vision
escalations spent, `chips=0`. The vision tier described the shimmering row
plainly visible on screen five separate times and pressed it four times.

⛔ AND MY FIRST DIAGNOSIS WAS WRONG, which is worth recording because the
evidence that refuted it had been in the log the whole time. I read the misses,
saw the pass stop answering after the first minute, and built a fix on the theory
that `lub` — the bottom of the last user message in VIEWPORT coordinates — had
gone negative as the page scrolled, switching the structural pass off. The
panel-miss snapshot says `"lub": 202`, positive, in both captures twelve minutes
apart. The brief never moved. That rebuild was reverted before it went anywhere.

⛔⛔ THE ACTUAL CAUSE, from the two snapshots (19:11:22 and 19:13:23), whose
`anim` and `clip` are SELF-only readings:

    the live line   anim=TRUE  clip=TRUE   animKid=true
                    inter=false  inTurn=false  named=false
    the disclaimer  anim=false clip=false  animKid=false
    the model chip  anim=false clip=false  animKid=TRUE

Every arm of the qualifier — `named`, `anim && inTurn`, `inter && anim`,
`inter && wordy` — is false for that row. ChatGPT had stopped putting
`cot-v*-pinned-row` on the node and stopped wrapping it in a turn container, so
the two exact signals were simply gone, and `inter` found no button within six
levels.

⭐⭐ THE PAIR THAT WAS TRUE HAD NO ARM. The 08-18 split was right — a running
animation anywhere in the subtree matches the composer's model chip, and a static
gradient matches a finished thinking step, so neither half may decide alone. What
it never did was recombine them ON THE SAME ELEMENT. A node whose own animation
is running AND whose own text is clipped to a gradient is not a weak signal; it is
the definition of a live shimmering text row, and in this capture it is the only
node on the page that is both. The model chip fails on `animSelf`. A finished
step fails on `animSelf`. A dead gradient fails on `animSelf`.

⭐ Why the owner's two examples worked: "Searching the web" is a verb and
"Searched 20 websites" carries a number, so the WORDING walk could see them
without the structural pass. Every other label that phase — "Designed a research
brief", "Mapped product layers and scoped security applications", "Compared
security layers" — matches no wording anchor at all.

Run: pytest tests/test_p1_structural_anchor_0820.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from tests._domshim import NODE, el, js_constant, run_js  # noqa: E402

OPENER_SRC = inspect.getsource(research._open_chatgpt_activity_panel)

needs_node = pytest.mark.skipif(NODE is None, reason="node required to execute page JS")


def _js():
    return js_constant(research._open_chatgpt_activity_panel, "JS")


def _open(spec, skip_structural=False):
    return run_js(spec, _js(), skip_structural)["ret"]


# ── the 19:13:23 snapshot, replayed ─────────────────────────────────────────
#
# lub=202 (the user bubble bottom), the live row at y=242 with its own animation
# running and its own text gradient-clipped, the disclaimer at 306, the composer's
# model chip at 724 with an animated CHILD and nothing of its own. Every number
# and flag below is off the run's own panel-miss snapshot.

LIVE_LABEL = "Mapped product layers and scoped security applications"


def _disclaimer():
    return el("div", {"class": "mt-auto", "w": "300", "h": "24", "x": "300",
                      "y": "306"},
              "ChatGPT can make mistakes. Check important info.")


def _model_chip():
    """`animKid: true`, nothing on itself. This is the decoy the qualifier's
    refusal of a lone shimmer exists to stop, and it is why the new arm asks
    about the element itself rather than its subtree."""
    return el("div", {"w": "60", "h": "24", "x": "300", "y": "724"}, "", [
        el("span", {"anim": "shimmer", "w": "60", "h": "24", "x": "300",
                    "y": "724"}, "Pro")])


def _live_row(label=LIVE_LABEL, *, anim=True, clip=True, y=242):
    attrs = {"w": "300", "h": "24", "x": "300", "y": str(y)}
    if anim:
        attrs["anim"] = "shimmer"
    if clip:
        attrs["clip"] = "text"
    return el("div", attrs, label)


def _page(*rows):
    """⭐ `main` CARRIES BULK, and it has to. Without it a `<main>` holding two
    short children is itself a candidate — 67 characters of text, two children,
    and an ellipsis somewhere inside it — so the walk pressed the whole page
    container and a "the composer is excluded" test failed for a reason that had
    nothing to do with composers. A real conversation has hundreds of nodes; a
    fixture only proves something if it answers the way the real thing does."""
    return el("body", {"w": "1440", "h": "900", "x": "0", "y": "0"}, "", [
        el("main", {"w": "1440", "h": "900", "x": "0", "y": "0"}, "", [
            el("div", {"data-message-author-role": "user", "w": "600", "h": "60",
                       "x": "300", "y": "142"},
               "NemoClaw vs NemoHermes vs Nemotron"),
            *rows,
            el("div", {"class": "markdown", "w": "800", "h": "1200", "x": "300",
                       "y": "800"},
               "The conversation body, which on a live page runs to pages. " * 10),
        ])])


# ── 1. the capture that went unpressed for twelve minutes ────────────────────

class TestTheRunsOwnSnapshot:

    @needs_node
    def test_the_live_row_is_pressed(self):
        """⛔ THE BUG. Before the pair had an arm, this exact page produced
        `no_match` twenty-three times while the row sat on screen shimmering."""
        got = _open(_page(_live_row(), _disclaimer(), _model_chip()))
        assert got.get("clicked") is True, got
        assert got.get("label") == LIVE_LABEL, got
        assert got.get("anchor") == "structural", got

    @needs_node
    def test_the_labels_no_wording_anchor_can_see(self):
        """The whole phase's labels were past-tense summaries. None matches a verb
        prefix, a number, an ellipsis, or thinking/reasoning/researching — so with
        the structural pass refusing them, no path could find the row."""
        for label in ("Designed a research brief",
                      "Mapped product layers and scoped security applications",
                      "Compared security layers",
                      "Scoping security applications"):
            got = _open(_page(_live_row(label), _disclaimer(), _model_chip()))
            assert got.get("clicked") is True, (label, got)
            assert got.get("label") == label, (label, got)

    @needs_node
    def test_the_two_labels_that_did_work_still_work(self):
        """The owner's own examples. These reach the WORDING walk on their own,
        which is why they were the only two ever pressed — so they must keep
        being pressed."""
        for label in ("Searching the web", "Searched 20 websites"):
            got = _open(_page(_live_row(label), _disclaimer(), _model_chip()))
            assert got.get("clicked") is True, (label, got)


# ── 2. the arm is narrow, and the decoys prove it ───────────────────────────

class TestItRefusesEverythingElseOnThatPage:

    @needs_node
    def test_the_composer_model_chip_is_not_the_strip(self):
        """⛔ `animKid: true` and nothing of its own. Asking the SUBTREE about the
        shimmer is what makes this chip look like the strip, and it is the reason
        a lone shimmer has never been allowed to qualify."""
        got = _open(_page(_disclaimer(), _model_chip()))
        assert got.get("clicked") is not True, got
        assert got.get("reason") == "no_match", got

    @needs_node
    def test_a_finished_step_keeps_its_gradient_and_is_still_refused(self):
        """The 08-18 lesson, which this change must not undo: ChatGPT's completed
        thinking steps keep the gradient class and just stop moving. Clipped text
        with no running animation of its own is a dead line."""
        got = _open(_page(_live_row("Structured security analysis", anim=False),
                          _disclaimer()))
        assert got.get("clicked") is not True, got

    @needs_node
    def test_a_running_animation_with_no_gradient_of_its_own_is_refused(self):
        """The other half. Something merely animating near the top of the
        conversation is not a text row — plenty of chrome animates on load."""
        got = _open(_page(_live_row("Some animated banner", clip=False),
                          _disclaimer()))
        assert got.get("clicked") is not True, got

    @needs_node
    def test_the_census_names_the_refusal(self):
        got = _open(_page(_disclaimer(), _model_chip()))
        assert got.get("structRan") is True, got
        assert int(got.get("structInBand") or 0) >= 1, got
        assert int(got.get("structQualified") or 0) == 0, got


# ── 3. the exact signal still outranks the heuristic one ────────────────────

class TestTheNamedRowStillWins:
    """⛔ Found by mutation: nothing asserted that ChatGPT's own name for the row
    outranks a mere shimmer. It could not be caught by the fixtures above, because
    on the build this run measured `named` is false — the test id is gone. It is
    still shipped on other builds, and on those the new arm now competes with it,
    so the ordering has to be pinned rather than assumed."""

    @needs_node
    def test_the_named_row_beats_a_shimmering_stranger(self):
        named = el("div", {"data-testid": "cot-v5-pinned-row", "w": "300",
                           "h": "24", "x": "300", "y": "260"},
                   "Structured the research brief")
        shimmer = el("div", {"anim": "shimmer", "clip": "text", "w": "300",
                             "h": "24", "x": "300", "y": "242"},
                     "Some other shimmering row")
        got = _open(_page(shimmer, named, _disclaimer()))
        assert got.get("clicked") is True, got
        assert got.get("label") == "Structured the research brief", got

    @needs_node
    def test_and_it_wins_even_sitting_lower_on_the_page(self):
        """The distance penalty must not be able to outweigh four points of exact
        naming — the shimmer here is nearer the anchor and still must not win."""
        named = el("div", {"data-testid": "cot-v5-pinned-row", "w": "300",
                           "h": "24", "x": "300", "y": "500"},
                   "Structured the research brief")
        shimmer = el("div", {"anim": "shimmer", "clip": "text", "w": "300",
                             "h": "24", "x": "300", "y": "220"},
                     "Some other shimmering row")
        got = _open(_page(shimmer, named, _disclaimer()))
        assert got.get("label") == "Structured the research brief", got


# ── 4. widening what qualifies cannot start pressing the report ─────────────

class TestItStillRefusesTheAgentsOwnReport:

    @needs_node
    def test_a_shimmering_cell_in_the_rendered_markdown_is_refused(self):
        """⛔ Twelve presses in one phase once landed on a markdown table cell of
        ChatGPT's own output. That exclusion lived only in the WORDING walk; a new
        qualifying arm in the structural pass needs it here too, which is the
        one-of-several-paths shape this file warns about twice."""
        body = "Report body, which on a live page runs to pages. " * 8
        got = _open(_page(
            el("div", {"class": "markdown", "w": "800", "h": "600", "x": "300",
                       "y": "242"}, body, [
                el("table", {"w": "700", "h": "300", "x": "300", "y": "260"}, "", [
                    el("td", {"anim": "shimmer", "clip": "text", "w": "200",
                              "h": "24", "x": "300", "y": "260"},
                       "Small reasoning safety classifier")])])))
        assert got.get("clicked") is not True, got
        assert int(got.get("structProse") or 0) >= 1, got

    @needs_node
    def test_the_composer_and_page_chrome_stay_excluded(self):
        got = _open(_page(
            el("form", {"w": "800", "h": "80", "x": "300", "y": "242"}, "", [
                el("div", {"anim": "shimmer", "clip": "text", "w": "200",
                           "h": "24", "x": "300", "y": "242"},
                   "Searching for updates...")])))
        assert got.get("clicked") is not True, got


# ── 4b. the container the chips actually live in ────────────────────────────

class TestTheInlineWalkerAcceptsATurnTestid:
    """⛔⛔ From the 08-20 e2e. The scraper was never blind — fed the captured chip
    row it returns 7 chips, 7 hostnames and drops "16 more". It just never RAN:
    it resolves the turn as an <article> or an assistant-role element, and these
    chips live under a SECTION carrying `data-testid="conversation-turn-2"`. No
    article, no assistant role, so it returned null and the caller read zero.

    The proof is one second wide, from two probes on the same page:
        21:46:35  miss #2 … chips 0->0
        21:46:35  snapshot: docs.nvidia.com, hermes-agent.org, github.com, …
    Every one of those rows reported `inTurn: true` — which is that selector."""

    HOSTS = ["docs.nvidia.com", "hermes-agent.org", "developer.nvidia.com",
             "github.com", "www.nvidia.com", "build.nvidia.com",
             "www.lasso.security", "16 more"]

    def _kids(self):
        rows = [el("div", {"class": "text-token-text-tertiary", "anim": "shimmer",
                           "clip": "text", "w": "300", "h": "24", "x": "300",
                           "y": "242"}, "Searching the web")]
        rows += [el("div", {"class": "flex", "w": "140", "h": "22", "x": "300",
                            "y": str(278 if i < 5 else 307)}, h)
                 for i, h in enumerate(self.HOSTS)]
        return rows

    def _page(self, *kids):
        return el("body", {"w": "1440", "h": "900"}, "", [
            el("main", {"w": "1440", "h": "900"}, "", [
                el("div", {"data-message-author-role": "user", "w": "600",
                           "h": "60", "x": "300", "y": "142"}, "the brief"),
                *kids])])

    def _walk(self, spec):
        return run_js(spec, research._CHATGPT_INLINE_ACTIVITY_JS)["ret"]

    @needs_node
    def test_a_section_turn_with_no_article_is_read(self):
        out = self._walk(self._page(
            el("section", {"data-testid": "conversation-turn-2", "w": "800",
                           "h": "400", "x": "300", "y": "230"}, "", self._kids())))
        assert out is not None, "the walker bailed out on the live shape"
        assert out["chips"] == 7, out
        assert out["chip_row"] is True, out
        assert "docs.nvidia.com" in out["source_hosts"], out

    @needs_node
    def test_the_count_chip_is_not_a_hostname(self):
        out = self._walk(self._page(
            el("section", {"data-testid": "conversation-turn-2", "w": "800",
                           "h": "400", "x": "300", "y": "230"}, "", self._kids())))
        assert "16 more" not in out["source_hosts"], out["source_hosts"]

    @needs_node
    def test_a_turn_holding_the_users_own_message_is_refused(self):
        """⭐ This testid is on USER turns too. Before the assistant's turn
        renders, the last match would be the brief we pasted — and a brief full
        of hostnames would be read as ChatGPT's sources."""
        out = self._walk(self._page(
            el("section", {"data-testid": "conversation-turn-1", "w": "800",
                           "h": "80", "x": "300", "y": "150"}, "", [
                el("div", {"data-message-author-role": "user", "w": "600",
                           "h": "60", "x": "300", "y": "150"},
                   "compare docs.example.com and github.com")])))
        assert out is None, out

    @needs_node
    def test_an_article_still_answers_first(self):
        """⭐ The new arm is LAST. `article` has the success record; this only
        picks up pages the old two abandoned."""
        out = self._walk(self._page(
            el("article", {"data-testid": "conversation-turn-2", "w": "800",
                           "h": "400", "x": "300", "y": "230"}, "", self._kids())))
        assert out["dbg"]["scope"] == "article", out["dbg"]


# ── 5. a miss now names its own gate ────────────────────────────────────────

class TestAMissNamesTheGate:

    def test_a_pass_that_never_ran_says_so(self):
        line = research._chatgpt_structural_census({"reason": "no_match"})
        assert "DID NOT RUN" in line, line

    def test_it_names_ONE_cause_and_the_right_one(self):
        """⛔⛔ My own line, and it committed the sin the function it lives in
        documents fixing: it said "no turn and no on-screen user message" for
        every non-run. In the 08-20 e2e it printed exactly that while every
        snapshot in the same run read `lub: 202` — so the cause it named was
        impossible, and the real one (the caller asking to skip) went unsaid."""
        skipped = research._chatgpt_structural_census(
            {"reason": "no_match", "structSkip": "caller asked to skip"})
        no_anchor = research._chatgpt_structural_census(
            {"reason": "no_match", "structSkip": "no user message on screen"})
        assert "caller asked to skip" in skipped, skipped
        assert "no user message on screen" in no_anchor, no_anchor
        assert skipped != no_anchor
        for line in (skipped, no_anchor):
            assert "no turn" not in line, line

    def test_an_unrecorded_reason_says_that_rather_than_guessing(self):
        line = research._chatgpt_structural_census({"reason": "no_match"})
        assert "not recorded" in line, line

    @needs_node
    def test_the_PAGE_actually_fills_the_reason_in(self):
        """⛔⛔ Found by mutation, and it is the third time today: the two tests
        above hand the renderer a `structSkip` themselves, so they pass whether or
        not the page ever sets one. Pin the PRODUCER — that is the whole
        `helper-pinned-caller-not` lesson, and I keep re-learning it.

        Nothing clickable on the page, so the walk returns its miss diagnostic
        rather than clicking and returning early."""
        quiet = el("body", {"w": "1440", "h": "900", "x": "0", "y": "0"}, "", [
            el("main", {"w": "1440", "h": "900", "x": "0", "y": "0"}, "", [
                el("div", {"data-message-author-role": "user", "w": "600",
                           "h": "60", "x": "300", "y": "142"}, "the brief"),
                el("div", {"class": "markdown", "w": "800", "h": "600",
                           "x": "300", "y": "260"},
                   "Report body, which on a live page runs to pages. " * 8)])])
        asked_to_skip = _open(quiet, skip_structural=True)
        assert asked_to_skip.get("structSkip") == "caller asked to skip", asked_to_skip

        off_screen = el("body", {"w": "1440", "h": "900", "x": "0", "y": "0"}, "", [
            el("main", {"w": "1440", "h": "900", "x": "0", "y": "0"}, "", [
                el("div", {"data-message-author-role": "user", "w": "600",
                           "h": "60", "x": "300", "y": "-900"}, "scrolled away"),
                el("div", {"class": "markdown", "w": "800", "h": "600",
                           "x": "300", "y": "260"},
                   "Report body, which on a live page runs to pages. " * 8)])])
        scrolled = _open(off_screen)
        assert scrolled.get("structSkip") == "no user message on screen", scrolled

        # and the census renders each of them differently, end to end
        a = research._chatgpt_structural_census(asked_to_skip)
        b = research._chatgpt_structural_census(scrolled)
        assert a != b and "not recorded" not in a and "not recorded" not in b, (a, b)

    def test_a_pass_that_ran_reports_its_band_and_what_it_threw_out(self):
        line = research._chatgpt_structural_census(
            {"structRan": True, "structAnchor": "lub", "structInBand": 3,
             "structNoSignal": 2})
        assert "in-band=3" in line and "no-signal=2" in line, line

    def test_zero_counters_are_left_out(self):
        """⭐ Wave 2's lesson applies to wave 1's fix: this renders on a per-tick
        DEBUG line, so it adds a clause, not a table."""
        line = research._chatgpt_structural_census(
            {"structRan": True, "structAnchor": "lub", "structInBand": 1})
        assert "off-band" not in line and "prose" not in line, line
        assert len(line) < 60, line

    def test_the_three_states_the_old_line_could_not_tell_apart(self):
        """Twenty-three identical lines, three different pages. The old miss line
        carried `walked` and `prose`, and neither is ever touched by this pass —
        so it could not say whether the pass had even run."""
        base = {"reason": "no_match", "walked": 862, "roots": 1, "contexts": 1}
        never = research._panel_miss_reason({**base, "structRan": False})
        empty = research._panel_miss_reason(
            {**base, "structRan": True, "structAnchor": "lub", "structInBand": 0})
        refused = research._panel_miss_reason(
            {**base, "structRan": True, "structAnchor": "lub", "structInBand": 4,
             "structNoSignal": 4})
        assert len({never, empty, refused}) == 3
        assert "in-band=4" in refused and "no-signal=4" in refused


# ── 6. the shape of the fix, pinned ─────────────────────────────────────────

class TestTheShapeOfTheFix:

    def test_the_self_only_readings_exist_and_are_separate(self):
        """The broadened `anim`/`clip` ask about the parent and twelve children,
        which is what makes each too weak to decide. The pair must be asked about
        the ELEMENT, or the model chip qualifies."""
        assert "const animSelf = shimmers(el);" in OPENER_SRC
        assert "const clipSelf = clipped(el);" in OPENER_SRC

    def test_the_pair_qualifies_and_neither_half_does_alone(self):
        qual = OPENER_SRC[OPENER_SRC.index("const qualifies = (h) =>"):
                          OPENER_SRC.index("const qualifiesWeak")]
        assert "(h.animSelf && h.clipSelf)" in qual, qual
        assert "|| h.animSelf" not in qual and "|| h.clipSelf" not in qual, (
            "one half of the shimmer qualifies on its own — a lone running "
            "animation matches the composer's model chip, and a lone gradient "
            "matches a finished thinking step"
        )

    def test_the_wording_anchors_were_not_widened(self):
        """⛔ The temptation this fix must not take. The file's own note says five
        prior commits kept expanding the verb regex "with no end in sight", and
        the 08-19 ellipsis retraction is the same lesson."""
        verb = OPENER_SRC[OPENER_SRC.index("const VERB_ONLY"):]
        verb = verb[:verb.index(";")]
        for word in ("mapped", "designed", "compared", "scoped", "structured"):
            assert word not in verb.lower(), (
                f"{word!r} was added to the verb anchor — that is the arms race "
                "this file has already lost five times"
            )

    def test_the_viewport_band_is_untouched(self):
        """⭐ My first fix moved this, on a theory the snapshot refutes: `lub` was
        202 all phase, so the band never rejected anything. Pinned here so the
        wrong fix cannot come back as a cleanup."""
        assert "const offTop = r.top - lub;" in OPENER_SRC
        assert "if (!skipStructural && lub > 0) {" in OPENER_SRC
