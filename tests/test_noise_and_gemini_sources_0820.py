"""Four false alarms, one dead selector arm, and two shim gaps that hid it.

OWNER, 2026-08-20, after I reported three "problems" off the 08-19 run that were
not problems: *"Maybe the logging is raising false alarms. Please go through
that."* They were right on all three, and the exercise found one real defect.

## The false alarms

* **The queued→ongoing 403.** A WARN plus a paragraph of transaction diagnostics,
  every run, for a write that is never needed: the caller's own comment records
  the flip failing on EVERY run in the corpus — twenty occurrences, zero
  successes — and the fallback plain-read resolving the status every time,
  because the app has already set it. Nobody can act on it and nothing is lost.
  Now DEBUG, full detail, ONCE per process, keyed on the root cause's class so a
  NEW failure class still speaks.
* **Claude's "panel still not detected".** Logged at 19:41:12. At 19:41:16 the
  vision tier reported the panel open with the report in it; at 19:41:20 we
  extracted 39,831 characters out of it. The panel was open — our probe could not
  see it, and the probe is the thing that wrote to the log. Now DEBUG, and the
  wording no longer asserts a closed panel. ⭐ The probe itself is NOT touched:
  the owner's instruction was to fix the alarm, not the code behind it.

## ⛔⛔ The real defect the exercise found

Gemini's source scan ends its selector list with `a[href*="http"]:not(…)` — which
matches ANCHORS — and then did this:

    const a = s.querySelector ? s.querySelector('a') : s;

`querySelector` searches DESCENDANTS, so an `<a>` always answered null and every
match was dropped. The broadest arm of the selector contributed nothing; only
container classes could ever yield a URL. Gemini-only (the idiom appears once).

## ⛔⛔ And TWO shim gaps meant no test could have caught it

1. **`:not()` was unmatchable.** The shim's qualifier pattern never accepted a
   `:`, so any selector carrying `:not()` matched NOTHING — silently. Three
   production selectors use it.
2. **A dot inside an attribute VALUE was read as a class selector.**
   `[href*="accounts.google"]` was taken to also require `class="google"`, so it
   could never match anything. An exclusion list that cannot exclude looks exactly
   like one that works.

Both had to be fixed before the Gemini fix could be measured at all — the arm was
dead in production AND unmatchable in the harness, and the two look identical
from the outside.

Run: pytest tests/test_noise_and_gemini_sources_0820.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from tests._domshim import NODE, el, evaluate_js, run_js  # noqa: E402

GEM_SCRAPE = inspect.getsource(research.scrape_progress_gemini)
POLL_SRC = inspect.getsource(research.poll_all_agents_round_robin)
WORKER_SRC = inspect.getsource(research.job_worker_loop) if hasattr(
    research, "job_worker_loop") else ""

needs_node = pytest.mark.skipif(NODE is None, reason="node required to execute page JS")


def _scrape(spec):
    return run_js(spec, evaluate_js(research.scrape_progress_gemini))["ret"]


def _report(*anchors):
    """A finished Gemini report: prose plus citation anchors, as the DOM has it."""
    return el("body", {"w": "1440", "h": "900", "x": "0", "y": "0"}, "", [
        el("message-content", {"w": "800", "h": "600", "x": "100", "y": "100"},
           "The report body, running to pages on a live page.", list(anchors))])


def _a(href, y=200):
    return el("a", {"href": href, "w": "100", "h": "20", "x": "100", "y": str(y)},
              href.split("//")[-1][:20])


# ── 1. the dead arm ─────────────────────────────────────────────────────────

class TestGeminiFindsItsCitations:

    @needs_node
    def test_citation_anchors_are_counted(self):
        """⛔ THE BUG. Every one of these was dropped: the selector matched the
        anchor, the code asked the anchor for a child anchor, got null, moved on.
        The 08-19 run reported sources=0 on an 82,817-character report."""
        r = _scrape(_report(_a("https://nvidia.com/nemo"),
                            _a("https://github.com/nvidia", 230)))
        assert r["sources"] == 2, r
        assert sorted(r["source_urls"]) == ["https://github.com/nvidia",
                                            "https://nvidia.com/nemo"], r

    @needs_node
    def test_googles_own_urls_are_still_excluded(self):
        """The exclusion list has to keep working — and until the shim learned
        about dots in attribute values, it never had."""
        r = _scrape(_report(_a("https://nvidia.com/nemo"),
                            _a("https://accounts.google.com/signin", 230)))
        assert r["source_urls"] == ["https://nvidia.com/nemo"], r

    @needs_node
    def test_geminis_own_conversation_url_is_not_a_source(self):
        """⭐ The panel walker has always dropped these; the document-wide arm did
        not, so the conversation's own link counted as a citation. Two paths, one
        rule."""
        r = _scrape(_report(_a("https://nvidia.com/nemo"),
                            _a("https://gemini.google.com/app/1105b338eb377d76", 230)))
        assert r["source_urls"] == ["https://nvidia.com/nemo"], r

    @needs_node
    def test_a_citation_CONTAINER_still_resolves_to_the_anchor_inside_it(self):
        """⛔ Found by mutation. Taking the element unconditionally fixes the
        anchor case and breaks the container case — `.source-card` and `.citation`
        wrap their link, so their own href is empty and the URL is dropped. The
        same loss, from the other direction."""
        card = el("div", {"class": "source-card", "w": "200", "h": "40",
                          "x": "100", "y": "200"}, "", [
            el("a", {"href": "https://nvidia.com/from-a-card", "w": "100",
                     "h": "20", "x": "100", "y": "200"}, "NVIDIA")])
        r = _scrape(_report(card))
        assert r["source_urls"] == ["https://nvidia.com/from-a-card"], r

    @needs_node
    def test_a_container_cannot_smuggle_an_excluded_host_past_the_list(self):
        """⛔⛔ Found the moment the anchor arm started working. The `:not(...)`
        exclusion guards only the ANCHOR arm; a container arm resolves to its
        inner <a> and had no equivalent guard, so a `.source-card` wrapping
        accounts.google was admitted as a citation. The guard is on the RESOLVED
        URL now — one rule, applied where the URL actually is."""
        card = el("div", {"class": "source-card", "w": "200", "h": "40",
                          "x": "100", "y": "200"}, "", [
            el("a", {"href": "https://accounts.google.com/signin", "w": "100",
                     "h": "20", "x": "100", "y": "200"}, "sign in")])
        assert _scrape(_report(card))["source_urls"] == [], "excluded host smuggled in"

    def test_the_host_pattern_survives_python_string_escaping(self):
        """⚠ This JS lives in a NON-RAW Python string. A single backslash before a
        dot is an invalid Python escape: it survives today with a warning and
        breaks on a later Python — and on 08-19 the same trap turned a
        word-boundary `\\b` into a literal BACKSPACE, so the match silently found
        nothing. Assert what the BROWSER receives, not what the file shows."""
        js = evaluate_js(research.scrape_progress_gemini)
        assert r"accounts\.google" in js, "the browser gets a mangled pattern"
        assert r"gemini\.google" in js

    @needs_node
    def test_a_report_with_no_citations_still_reports_zero(self):
        """The 08-19 report genuinely had none — its only http strings were code
        examples. Zero must stay reachable, or the fix just inflates."""
        r = _scrape(_report())
        assert r["sources"] == 0, r


# ── 2. the provenance, so the next zero can be diagnosed ────────────────────

class TestTheCountSaysWhereItCameFrom:

    @needs_node
    def test_page_and_panel_are_reported_separately(self):
        r = _scrape(_report(_a("https://nvidia.com/nemo"),
                            _a("https://github.com/nvidia", 230)))
        assert r["src_page"] == 2 and r["src_panel"] == 0, r

    @needs_node
    def test_the_two_halves_add_up_to_the_total(self):
        r = _scrape(_report(_a("https://nvidia.com/a"), _a("https://nvidia.com/b", 230),
                            _a("https://accounts.google.com/x", 260)))
        assert r["src_page"] + r["src_panel"] == r["sources"], r

    def test_the_poll_loop_logs_it_for_gemini_only(self):
        at = POLL_SRC.index("[Gemini] source tracking:")
        decl = POLL_SRC[POLL_SRC.index('if name == "Gemini" and scrape_ok:'):at]
        assert "gemini_src_last" in decl, decl

    def test_it_logs_on_change_only(self):
        """⭐ Wave 2's lesson: a per-cycle restatement of an unchanging number is
        a true statement carrying one bit. This is the third consumer of that
        rule."""
        at = POLL_SRC.index('if name == "Gemini" and scrape_ok:')
        block = POLL_SRC[at:at + 700]
        assert 'if _gsrc != p.get("gemini_src_last"):' in block, block

    def test_the_line_names_all_four_numbers(self):
        at = POLL_SRC.index("[Gemini] source tracking:")
        line = POLL_SRC[at:at + 220]
        for part in ("page=", "panel=", "searches="):
            assert part in line, (part, line)


# ── 3. the false alarms ─────────────────────────────────────────────────────

class TestTheFlip403IsNotAnAlarm:

    def test_it_is_debug_not_warn(self):
        src = inspect.getsource(research)
        at = src.index("could not open the queued→ongoing transaction")
        tail = src[at:at + 700]
        assert '"DEBUG"' in tail, tail
        assert '"WARN"' not in tail, tail

    def test_it_no_longer_claims_a_failure(self):
        src = inspect.getsource(research)
        assert "Failed to flip queued→ongoing" not in src, (
            "the line still opens by calling a compensated no-op a failure"
        )
        at = src.index("could not open the queued→ongoing transaction")
        assert "not a \nrun-affecting" in src[at:at + 900].replace(
            "run-affecting", "\nrun-affecting", 1) or "run-affecting" in src[at:at + 900]

    def test_it_speaks_once_per_process_keyed_on_the_cause(self):
        """⭐ Not silenced — kept at full detail, once. The root cause is still
        unnamed, so the day it changes class the new one has to speak."""
        s = research._FLIP_403_QUIET
        emit1, dropped1 = s.consider("flip-txn-refused", "PermissionDenied")
        emit2, dropped2 = s.consider("flip-txn-refused", "PermissionDenied")
        assert emit1 is True and dropped1 == 0
        assert emit2 is False, "the second identical refusal printed again"
        emit3, _ = s.consider("flip-txn-refused", "DeadlineExceeded")
        assert emit3 is True, "a NEW failure class must still speak"

    def test_the_log_is_actually_GATED_on_the_suppressor(self):
        """⛔ Found by mutation. My first test exercised the suppressor object
        directly, which passes whether or not the call site consults it — the
        `helper-pinned-caller-not` trap, exactly. Pin the gate."""
        src = inspect.getsource(research)
        at = src.index("could not open the queued→ongoing transaction")
        before = src[max(0, at - 400):at]
        assert "if _emit_flip:" in before, before[-200:]

    def test_the_suppressor_is_keyed_on_the_ROOT_CAUSES_CLASS(self):
        """⛔⛔ Also found by mutation, and the more important of the two: keying
        on a constant swallows a DIFFERENT failure class behind the first one's
        marker. The root cause here is still unnamed, so a change of class is
        precisely the signal we would be throwing away. An EXACT line, because a
        presence check cannot see a changed argument."""
        src = inspect.getsource(research)
        assert ('                "flip-txn-refused", '
                'f"{type(_root).__name__ if _root else type(e).__name__}")'
                in src), (
            "the suppressor is no longer keyed on the failure's class"
        )

    def test_the_genuinely_unresolved_path_is_still_a_warn(self):
        """⛔ The one case a person CAN act on: the transaction was refused AND
        the fallback read failed too, so nobody knows the status. That stays a
        WARN, or this change would be a silencing rather than a de-escalation."""
        src = inspect.getsource(research)
        at = src.index("the transaction was refused and the doc could")
        assert '"WARN"' in src[at:at + 300]
        at2 = src.index("the transaction was refused and the fallback")
        assert '"WARN"' in src[at2:at2 + 300]


class TestClaudesPanelProbeStopsAssertingAClosedPanel:

    def test_it_is_debug_now(self):
        src = inspect.getsource(research)
        at = src.index("the probe still cannot confirm the artifact")
        assert '"DEBUG"' in src[at:at + 300]

    def test_the_wording_no_longer_says_the_panel_is_shut(self):
        src = inspect.getsource(research)
        assert "CUA panel-open recovery ran but panel still not" not in src
        at = src.index("the probe still cannot confirm the artifact")
        line = src[at:at + 260]
        assert "probe gap" in line, line

    def test_the_probe_itself_was_not_touched(self):
        """⭐ The owner's instruction was explicit: fix the false alarm, do not
        mess with the code there. The recovery still runs and the tiers still
        attempt extraction."""
        src = inspect.getsource(research)
        assert "CUA panel-open recovery timed out after 120s" in src


# ── 4. the shim gaps that hid the defect ────────────────────────────────────

class TestTheShimCanNowSeeWhatProductionWrites:

    @needs_node
    def test_not_actually_excludes(self):
        spec = el("body", {}, "", [
            el("a", {"href": "https://ok.example/x", "w": "10", "h": "10"}, "ok"),
            el("a", {"href": "https://accounts.google.com/x", "w": "10", "h": "10"}, "no"),
        ])
        out = run_js(spec, """() => [...document.querySelectorAll(
            'a[href*="http"]:not([href*="accounts.google"])')].map(a => a.href)""")
        assert out["ret"] == ["https://ok.example/x"], out["ret"]

    @needs_node
    def test_a_dot_in_an_attribute_value_is_not_a_class_selector(self):
        """⛔⛔ `[href*="accounts.google"]` used to also require `class="google"`.
        Nothing has that, so the selector matched nothing — and an exclusion list
        that cannot exclude is indistinguishable from one that works."""
        spec = el("body", {}, "", [
            el("a", {"href": "https://accounts.google.com/x", "w": "10", "h": "10"}, "x")])
        out = run_js(spec, """() => document.querySelectorAll(
            '[href*="accounts.google"]').length""")
        assert out["ret"] == 1, out["ret"]

    @needs_node
    def test_a_real_class_selector_still_works(self):
        spec = el("body", {}, "", [
            el("div", {"class": "source-card", "w": "10", "h": "10"}, "a"),
            el("div", {"class": "other", "w": "10", "h": "10"}, "b")])
        out = run_js(spec, "() => document.querySelectorAll('.source-card').length")
        assert out["ret"] == 1, out["ret"]

    @needs_node
    def test_a_bare_not_means_anything_but(self):
        spec = el("body", {}, "", [
            el("div", {"class": "keep", "w": "10", "h": "10"}, "a"),
            el("div", {"class": "drop", "w": "10", "h": "10"}, "b")])
        out = run_js(spec, "() => document.querySelectorAll(':not(.drop)').length")
        assert out["ret"] == 1, out["ret"]
