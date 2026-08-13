"""One page label, spelled two ways, read by two halves of the same pipeline.

WHAT THIS IS ABOUT

ChatGPT renders a thinking-time header above a finished response. It used to say
"Thought for 1m 14s"; since 2026-08 it also says "Worked for 9m" / "Worked for
16m 26s". Five places in this file read that header.

On 2026-08-11 ONE of them — `_classify_completion_verdict`, the Python parser
that reads the vision model's prose — was widened from the single literal
"thought for" to the verb family. The four page-side JS copies were not touched.

So for a day the pipeline held two vocabularies for one label: the vision
classifier could recognise "Worked for 16m 26s" and every DOM-side check,
looking at the same page, could not.

⭐ WHAT THAT ACTUALLY COST, STATED HONESTLY

This is NOT the cause of the 44-minute P1 stall on 2026-08-12. On that run the
host DOM check returned "not generating" correctly on every read — it reached
its `.result-streaming` fallback and answered False. The 44 minutes came from
the CUA confirm loop above it (see test_cua_confirm_budget_0812.py).

What the split DID leave exposed is the P2 twin of the same incident, plus two
smaller short-circuits:

  * `_CHATGPT_DONE_PROBE_JS.thoughtFor` is a POSITIVE done marker for
    `detect_completion_chatgpt`, which is how Phase 2's round-robin decides an
    agent has finished. A run whose only done marker is the current label was
    invisible to it.
  * The host check and its diagnostic twin both use the badge to short-circuit
    a residual `data-is-streaming="true"` attribute. Without a matching badge a
    finished page with that leftover attribute reads as still generating — the
    exact class of residual-chrome false-positive the 2026-05-14 notes describe.

WHAT THESE TESTS PIN

  1. There is ONE pattern. The Python regex and the JS literal are built from
     the same source, and no hand-written copy of the old literal survives.
  2. The current label is recognised by the JS, executed under node — not
     asserted against the source text.
  3. Phase 2's completion detector calls a run done when the current label is
     the only done marker present.
  4. The host verify and its diagnostic twin agree, and the badge still beats a
     residual streaming attribute.
  5. ⛔ The time unit is still REQUIRED. It is what makes widening the verb
     family safe: "thought for 3" is rare in prose, but a research brief writes
     "worked for 3 years" as an ordinary sentence, and a unitless match would
     turn the report's own text into a completion marker — a false COMPLETE,
     which every note in research.py records as the strictly worse failure.
"""
import asyncio
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from _domshim import el, run_js  # noqa: E402
from conftest import code_only_deep  # noqa: E402

# The label the live page carried at 10:07 on 2026-08-12, quoted by the vision
# model in the same breath as "no stop button".
LIVE = "Worked for 16m 26s"
# The label the pattern was written for in 2026-06.
LEGACY = "Thought for 1m 14s"

# Every verb the family accepts, in the header shape.
FAMILY = [LIVE, LEGACY, "Reasoned for 45 seconds", "Researched for 5m 1s",
          "Worked for 9m", "Thought for 23 seconds"]

# The same verbs in ordinary report prose. A brief about a company writes every
# one of these. None may read as a completion marker.
PROSE = [
    "The team worked for 3 years on the acquisition",
    "She researched for 2 decades before publishing",
    "He thought for a moment about the tradeoff",
    "The committee reasoned for several pages that the merger was sound",
    # the shape closest to the badge: a bare number, no unit
    "worked for 3 teams across the region",
    # ── the three below each pin ONE boundary of the pattern, and every one of
    # them was found by mutation: the first draft of this file asserted only the
    # cases above, and a pattern loosened at any of these three edges still
    # passed. They are ordinary sentences in a research brief, which is the
    # point — this pattern is read against the whole rendered report.
    #
    # the VERB family is closed. Opened to \w+, this reads as a finished header.
    "The outage lasted for 3 hours before the feed recovered",
    # the TRAILING boundary. Without it, "3 h" matches inside "3 hourly".
    "The team worked for 3 hourly briefings that week",
    # the LEADING boundary. Without it, "thought for 5 minutes" matches inside
    # "rethought".
    "He rethought for 5 minutes and changed his mind",
]


def _body(text, *, attrs=None, tag="div"):
    """A page whose only content is `text`, optionally on a marked-up node."""
    return el("body", kids=[el("main", kids=[el(tag, attrs=attrs or {}, text=text)])])


# ── 1. one pattern, two engines ──────────────────────────────────────────────

def test_the_python_regex_and_the_js_literal_come_from_one_source():
    """Not "they happen to agree" — they are the same string.

    A test that compared two hand-written patterns would pass on the day both
    were correct and say nothing about the day one of them moved, which is
    precisely what happened between 2026-08-11 and 2026-08-12."""
    assert research._THINKING_TIME_HEADER.pattern == research._THINKING_TIME_HEADER_SRC
    assert research._THINKING_TIME_HEADER_JS == f"/{research._THINKING_TIME_HEADER_SRC}/i"


def test_no_hand_written_copy_of_the_old_literal_survives():
    """The anti-drift guard, and the reason this file exists.

    `code_only_deep` blanks comments AND docstrings AND the `//` lines inside
    the embedded JS: the fix comments above every one of these call sites quote
    the literal they replaced, and a presence assertion cannot tell code from
    prose. That trap has bitten this repo on both sides of the stack.

    Scoped to REGEX LITERALS rather than the bare phrase. The phrase itself is
    legitimate in a CUA mission prompt, which names the label to a vision model
    in English; what must never come back is a second hand-written PATTERN."""
    src = code_only_deep(Path(research.__file__).read_text(encoding="utf-8"))
    stragglers = re.findall(r"/[a-z |()?:\\\\]*\bthought for\b[^\n]*?/i", src.lower())
    assert not stragglers, stragglers


def test_every_page_side_badge_check_goes_through_the_shared_pattern():
    """The positive half: not just "the old literal is gone" but "the new one is
    wired in, everywhere". Five payloads read this label in JS — the P2
    completion probe, the host verify, its DR-iframe walk, the diagnostic twin,
    and the corroborator probe — and each must substitute the shared pattern.

    Balanced rather than counted to a fixed number, so ADDING a sixth reader is
    fine and forgetting its substitution is not. A payload that ships the raw
    placeholder throws at `.test`/`.match` in the browser, in production, on
    paths that are wrapped in `except Exception:` — so it would degrade
    silently, which is this whole file's failure mode one layer down."""
    src = code_only_deep(Path(research.__file__).read_text(encoding="utf-8"))
    subs = src.count('.replace("__DONE_BADGE_RE__", _THINKING_TIME_HEADER_JS)')
    in_js = src.count("__DONE_BADGE_RE__") - subs
    assert subs >= 4, f"only {subs} substitutions — the wiring was removed"
    assert in_js == subs, f"{in_js} JS readers but {subs} substitutions"


def test_no_module_level_payload_ships_the_placeholder():
    """The runtime half of the check above: what the module actually holds.

    A source count can be satisfied by a substitution that runs on the wrong
    string; this reads the values production hands to `page.evaluate`."""
    for name in ("_CHATGPT_DONE_PROBE_JS", "_DONE_BADGE_PROBE_JS"):
        payload = getattr(research, name)
        assert "__DONE_BADGE_RE__" not in payload, f"{name} ships raw"
        assert research._THINKING_TIME_HEADER_SRC in payload, f"{name} lost the pattern"


def test_the_shared_source_is_not_a_bare_verb_list():
    """A positive control on the guard above: the constant must actually carry
    the unit alternation, not just the verbs. Deleting the unit half is the
    mutation this whole file is guarding, and a test that only checked the
    verbs would survive it."""
    assert "minutes" in research._THINKING_TIME_HEADER_SRC
    assert "seconds" in research._THINKING_TIME_HEADER_SRC


# ── 2. the JS recognises the current label, executed under node ──────────────

@pytest.mark.parametrize("label", FAMILY)
def test_the_probe_js_reads_every_header_form_as_done(label):
    ret = run_js(_body(label), research._CHATGPT_DONE_PROBE_JS)["ret"]
    assert ret["thoughtFor"] is True, label


@pytest.mark.parametrize("sentence", PROSE)
def test_the_probe_js_reads_report_prose_as_nothing(sentence):
    """⛔ The false-COMPLETE guard. If this fails, widening the verb family has
    made the brief's own text into a done signal."""
    ret = run_js(_body(sentence), research._CHATGPT_DONE_PROBE_JS)["ret"]
    assert ret["thoughtFor"] is False, sentence


# ── 3. Phase 2's completion detector, end to end ─────────────────────────────

class _Ctx:
    """A frame/page context that runs the real JS against a real DOM spec."""

    def __init__(self, url, spec):
        self.url = url
        self.spec = spec
        self.calls = []

    async def evaluate(self, js, arg=None):
        self.calls.append(js)
        return run_js(self.spec, js, arg)["ret"]


class _Page(_Ctx):
    def __init__(self, spec, frames=()):
        super().__init__("https://chatgpt.com/c/abc", spec)
        self.main_frame = self
        self._frames = [self, *frames]

    @property
    def frames(self):
        return self._frames

    def is_closed(self):
        return False


def _finished_page(label):
    """A finished DR response whose ONLY done marker is the thinking-time
    header — no "Research completed" chip, no document panel, no stop button.

    That combination is not contrived: it is what a Pro + Extended Thinking
    answer looks like, and it is the shape the 2026-08 relabel made invisible."""
    return _Page(el("body", kids=[
        el("main", kids=[
            el("div", attrs={"data-message-author-role": "assistant"},
               text=f"{label}\n" + ("The brief runs to several thousand characters. " * 40)),
        ]),
    ]))


def test_phase_2_calls_a_run_done_on_the_current_label():
    """The P2 twin of the P1 stall: a finished agent the round-robin could not
    see, because the only marker on the page used the new verb."""
    done, reason, snap = asyncio.run(
        research.detect_completion_chatgpt(_finished_page(LIVE)))
    assert done is True, reason
    assert snap["text_len"] > 0


def test_phase_2_still_calls_the_old_label_done():
    done, reason, _snap = asyncio.run(
        research.detect_completion_chatgpt(_finished_page(LEGACY)))
    assert done is True, reason


def test_phase_2_does_not_call_a_run_done_on_prose_alone():
    """The same page with no header at all — only a sentence that contains a
    family verb. Nothing else on it says done, so nothing may."""
    done, _reason, _snap = asyncio.run(
        research.detect_completion_chatgpt(
            _finished_page("The team worked for 3 years on this")))
    assert done is False


# ── 4. the host verify and its diagnostic twin ───────────────────────────────

class _ScrollTolerantPage(_Page):
    """The real `verify_chatgpt_generating` scrolls before it decides.

    The shim has no `window.scrollTo`, so that payload is skipped — and the skip
    is COUNTED, because a fake that silently swallowed the decision payload too
    would make every assertion below pass against nothing."""

    def __init__(self, spec):
        super().__init__(spec)
        self.skipped = 0
        self.ran = 0

    async def evaluate(self, js, arg=None):
        if "scrollTo" in js:
            self.skipped += 1
            return None
        self.ran += 1
        return run_js(self.spec, js, arg)["ret"]


def _settled_with_streaming_residue(label):
    """A finished response carrying a leftover `data-is-streaming="true"`.

    This is the case the badge short-circuit exists for: with no stop button and
    no running animation, the attribute is residual chrome, and the header is
    what says so."""
    return _ScrollTolerantPage(el("body", kids=[
        el("main", attrs={"data-is-streaming": "true"}, kids=[
            el("div", text=f"{label}\nthe finished brief"),
        ]),
    ]))


def test_the_host_verify_reads_the_current_label_as_settled():
    page = _settled_with_streaming_residue(LIVE)
    assert asyncio.run(research.verify_chatgpt_generating(page)) is False
    assert page.ran == 1, "the decision payload never ran — the fake ate it"
    assert page.skipped == 1


def test_the_host_verify_still_reads_the_old_label_as_settled():
    page = _settled_with_streaming_residue(LEGACY)
    assert asyncio.run(research.verify_chatgpt_generating(page)) is False
    assert page.ran == 1


def test_the_host_verify_keeps_believing_the_streaming_attribute_without_a_badge():
    """The other half of the short-circuit. Deleting the badge check must not be
    the same as deleting the attribute check — with no header on the page, the
    residual attribute is the only evidence there is, and it still wins."""
    page = _settled_with_streaming_residue("no header here")
    assert asyncio.run(research.verify_chatgpt_generating(page)) is True


def test_the_diagnostic_twin_agrees_with_the_verify_it_explains():
    """The two are kept in sync BY HAND — research.py says so in the diag's own
    docstring. Drift between them mislabels every safety-net log line, and the
    reason string is what `_hard_stop_signal` is computed from.

    "no_hit" IS the diag's done answer: the JS returns "" and the caller's
    `or "no_hit"` names it. What matters downstream is that it does not start
    with a stop-signal prefix, so assert that too rather than only the string."""
    page = _settled_with_streaming_residue(LIVE)
    reason = asyncio.run(research._verify_chatgpt_generating_diag(page))
    assert reason == "no_hit"
    assert not reason.startswith(("stop_composer", "card_stop", "generic_stop_label"))


def test_the_diagnostic_twin_names_the_streaming_attribute_without_a_badge():
    page = _settled_with_streaming_residue("no header here")
    assert asyncio.run(
        research._verify_chatgpt_generating_diag(page)) == "data_streaming_attr"


# ── 5. the Python side reads the same family ─────────────────────────────────

@pytest.mark.parametrize("label", FAMILY)
def test_the_vision_classifier_reads_every_header_form_as_complete(label):
    text = f"There is no stop button visible. I can see \"{label}\" above the response."
    assert research._classify_completion_verdict(text) == "complete"


@pytest.mark.parametrize("sentence", PROSE)
def test_the_vision_classifier_reads_report_prose_as_nothing(sentence):
    """Ambiguous, not complete. The classifier's whole cost-asymmetry argument
    rests on prose never reaching the done branch."""
    assert research._classify_completion_verdict(sentence) == "ambiguous"
