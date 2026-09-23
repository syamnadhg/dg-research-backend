"""Claude P2 setup: the model popover must open ONLY when it has work to do.

Background (2026-07-30). `setup_claude_dr` opened the model popover on EVERY
run, unconditionally, because the Thinking toggle lived inside the Effort
submenu and had to be re-asserted each time (#745). Opus 5 removed that toggle,
so every run produced this pair of log lines back to back:

    Step 1 OK: model already Opus 5 (trigger) — NOT re-picking (#744)
    Step 1A OK: opened model popover                 <-- opened it anyway

followed by `Step 1D WARN: 'Thinking' toggle not found`, `Step 1C WARN: 'Max'
effort not found`, and then the CUA validate layer being invited in to "fix" the
quality knobs — where it clicked into the model menu a second time. That second
interaction is what the owner reported as "it opens the modal selector twice".

The trigger already carries BOTH facts ("Opus 5 Max"), so when it names the
model FAMILY and shows the target effort there is nothing behind the popover
left to set.

⚠ REVISED 2026-08-01. Skipping is right, but skipping FOREVER is how the account
gets stranded: the upgrade probe lives behind the popover, so a permanent skip
means a newer model is never discovered. A periodic check (`allow_probe` +
`model_probe_due`) now opens it on a cadence — once per interval, on the initial
setup call only. These tests pin BOTH halves: the skip on an ordinary run, and
the open on a due run.

These tests DRIVE the real coroutine against a scripted page and assert on
whether the popover-opening script was evaluated. A source-text assertion would
not do: the whole class of bug here is a decision that reads correct in source
and still fires, and this repo has been burned by exactly that before (37
rehydration tests once passed against a guaranteed crash).
"""
import asyncio

import pytest

import models
import research


# Distinctive fragments of the real scripts inside setup_claude_dr. Matching on
# these is what makes "did the popover open?" observable.
_POPOVER_OPEN_MARK = "trigger.click()"           # Step 1A: clicks the model trigger
# ⚠ NO CLOSING BRACE. This is an IDENTIFICATION mark, not a contract, and
# pinning the full parameter list made it one: adding `verbs`/`upsellWindow` for
# the upsell exclusion stopped it matching, so this double silently answered
# every pick with "nothing clickable" and six tests failed for a reason that had
# nothing to do with what they assert. The signature itself is pinned once, on
# purpose, in test_known_good_fallback.
_PICK_OPUS_MARK = "{pin, below, fam, triggerText"   # Step 1B: the picker
_PROBE_MARK = "menu: false"                      # Step 1B*: the read-only probe
# 2026-08-05 (review, f3): was `t === 'effort'`, a fragment of the old predicate. The
# candidate set is now filtered for anchors first — `li` is in it and claude.ai wraps
# conversation links in one, so a thread titled "Effort…" was reachable by a REAL
# press, which on a link navigates. The redundant equality went with the rewrite
# (`startsWith('effort')` always subsumed it).
_EFFORT_SUBMENU_MARK = "const linky = el =>"     # Step 1C: MARKS the Effort row
# ⚠ RE-ANCHORED 2026-08-17. Both literals moved with the fix, and both moved for
# the same reason: the gate used to walk the whole DOCUMENT for short rows (hence
# `t.length > 24`) and the picker compared against a hardcoded `'max effort'`. The
# gate now asks each OVERLAY separately — a portalled popper is last in document
# order, so the sidebar filled the old 20-row cap and the submenu was never
# reached — and the picker takes its tier from policy. `isRung` and `isWanted` are
# each unique to their script.
_SUBMENU_ROWS_MARK = "isRung"                    # Step 1C: did the submenu mount?
_THINKING_MARK = "isThinking"                    # Step 1D: the Thinking toggle probe
_EFFORT_SET_MARK = "isWanted"                    # Step 1C': selects the tier
_TRIGGER_READ_MARK = "trigger_text"              # Step 1: reads model + effort


def _vk(x):
    """The DOUBLE's own reading of a version's order: whole numbers split at the
    dot, trailing zeros dropped, a number read through its shortest text.

    ⛔ Deliberately NOT `models.version_key`. The double stands in for the PAGE,
    and the code under test compares with `version_key`; if the page borrowed it,
    a broken comparator would break both halves identically and every test here
    would still agree with itself."""
    if x is None or isinstance(x, bool):
        return None
    s = repr(float(x)) if isinstance(x, (int, float)) else str(x)
    try:
        parts = [int(p) for p in s.split(".")]
    except ValueError:
        return None
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _vt(x):
    """What the real page scripts RETURN for a row since 2026-09-23: the matched
    dotted text ("5.10", "5"), never a float. A test may still describe its menu
    with numbers; the page never answers with one."""
    return x if isinstance(x, str) else ".".join(str(p) for p in _vk(x))


class _Keyboard:
    def __init__(self, log):
        self._log = log

    async def press(self, key):
        self._log.append(("key", key))


class ScriptedPage:
    """Minimal page double. `evaluate` dispatches on distinctive fragments of the
    real script text, records every call, and returns scripted values.

    `trigger_text` is the crucial input: it is what the model-selector button
    reads on the live page, e.g. "Opus 5 Max" or just "Opus 5".
    """

    def __init__(self, trigger_text, *, chat_tab="chat", research_on=True,
                 offered=5.0, menu_mounts=True, rows=None, trigger_is_model_ctl=True,
                 popover_opens=True, row_label=None, effort_row_shows="effort max",
                 wanted_row=True, wanted_already=True):
        self.trigger_text = trigger_text
        # The Effort row read gap-aware (the script's `shows`), e.g. "effort low".
        self.effort_row_shows = effort_row_shows
        # Does the submenu offer the wanted tier's row at all (False = the 09-20
        # page: no 'max' row), and is it already the selected one?
        self.wanted_row = wanted_row
        self.wanted_already = wanted_already
        # How a picked row's LABEL reads (the real picker returns the row's
        # first 60 characters). Default "Opus <version>"; a test can hand in a
        # row whose version sits past the slice, so the label carries none.
        self.row_label = row_label or (lambda v: f"Opus {_vt(v)}")
        self.chat_tab = chat_tab
        self.research_on = research_on
        self.offered = offered          # highest version the open menu lists
        self.menu_mounts = menu_mounts  # False = the popover never renders rows
        self.rows = rows                # every version the menu offers
        # False = the element carrying the family word is NOT a model control
        # (a marketing/plan chip). Only matters for a VERSION-LESS label: a
        # numbered one is strong enough evidence to read page-wide.
        self.trigger_is_model_ctl = trigger_is_model_ctl
        self.popover_opens = popover_opens   # False = the trigger button is gone
        self.scripts = []           # every JS string evaluated, in order
        self.hovers = []            # real hovers, by selector
        self.presses = []           # real clicks, by selector
        self.effort_marked = False  # did the JS mark the Effort row?
        self.events = []            # keyboard presses
        self.keyboard = _Keyboard(self.events)
        self._picked = None

    def _trigger_version(self):
        """The trigger's version as the double's own ORDER key (see `_vk`)."""
        import re
        m = re.search(r"opus[^0-9]*([0-9]+(?:\.[0-9]+)?)", self.trigger_text, re.I)
        return _vk(m.group(1)) if m else None

    # -- helpers the tests assert on -------------------------------------
    def evaluated(self, mark):
        return any(mark in s for s in self.scripts)

    def count(self, mark):
        return sum(1 for s in self.scripts if mark in s)

    def picked(self):
        """The version the picker actually selected, or None if it selected
        nothing. Reading the OUTCOME is what makes the pin/below filters
        testable at all — asserting that the picker script merely ran cannot
        tell a correct selection from a wrong one."""
        return self._picked

    # -- the page API surface setup_claude_dr actually touches ------------
    async def query_selector(self, sel):
        return None  # no precise tools-menu selector matches; falls to the '+' detector

    async def hover(self, selector, timeout=None):
        if not self.effort_marked:
            raise RuntimeError(f"no element matches {selector}")
        self.hovers.append(selector)

    async def click(self, selector, timeout=None):
        # The real press. A submenu trigger opens on the pointer ARRIVING, so
        # the hover is the part that matters — but both are recorded so a
        # regression that drops one is visible.
        if not self.effort_marked:
            raise RuntimeError(f"no element matches {selector}")
        self.presses.append(selector)

    async def evaluate(self, script, arg=None):
        self.scripts.append(script)

        if _TRIGGER_READ_MARK in script:
            # Mirror the real script's own contract: the family word decides
            # whether a model is selected at all; the version is extra; and the
            # effort word counts only when it appears in that SAME text.
            import re
            fam = (arg or {}).get("fam", "opus")
            effort_word = (arg or {}).get("effortWord")
            has_fam = re.search(fam, self.trigger_text, re.I) is not None
            m = re.search(fam + r"[^0-9]*([0-9]+(?:\.[0-9]+)?)", self.trigger_text, re.I)
            # The matched TEXT, as the real script returns it since 2026-09-23.
            ver = m.group(1) if m else None
            # Mirror the JS: a version-LESS family word only counts when it sits
            # on something that looks like a model control.
            if ver is None and has_fam and not self.trigger_is_model_ctl:
                has_fam = False
            toks = re.split(r"[^a-z0-9.]+", self.trigger_text.lower())
            effort = (effort_word if (has_fam and effort_word
                                      and str(effort_word).lower() in toks) else None)
            return {"ver": ver, "fam": has_fam, "effort": effort,
                    "trigger_text": self.trigger_text if has_fam else ""}

        if _POPOVER_OPEN_MARK in script:
            return self.popover_opens
        if _PROBE_MARK in script:
            if not self.menu_mounts:
                return {"menu": False, "n": 0, "highest": None}
            return {"menu": True, "n": 1, "highest": _vt(self.offered)}
        if _PICK_OPUS_MARK in script:
            # ⚠ HONOUR THE ARGS. This used to return a canned hit regardless of
            # pin/below/triggerText, so the picker's exact-pin, strictly-older
            # and never-click-the-trigger filters were only ever checked by
            # source-substring assertions — inverting a comparison inside the JS
            # left every behavioural test green. Mirror the JS contract instead.
            # ⭐ 2026-09-23 — by version ORDER, and a pin/below may arrive as the
            # dotted text production now sends ("5.10") or as a legacy number;
            # the answer is always text, as the real script's is.
            a = arg or {}
            rows = list(self.rows if self.rows is not None else [self.offered])
            trig_k = self._trigger_version()
            pin_k, below_k = _vk(a.get("pin")), _vk(a.get("below"))
            if a.get("triggerText") and trig_k is not None:
                rows = [v for v in rows if _vk(v) != trig_k]   # never click the trigger
            hit = next((v for v in rows if pin_k is not None and _vk(v) == pin_k), None)
            if hit is not None:
                self._picked = hit
                return {"label": self.row_label(hit), "version": _vt(hit)}
            if pin_k is not None or below_k is not None:
                bound = below_k if below_k is not None else pin_k
                rows = [v for v in rows if _vk(v) < bound]
            if not rows:
                return None
            best = max(rows, key=_vk)
            self._picked = best
            return {"label": self.row_label(best), "version": _vt(best)}
        if _EFFORT_SUBMENU_MARK in script:
            # Did it MARK the row, or click it from in here? The distinction is
            # the whole fix, and the double has to feel it: an element that was
            # never marked is an element Playwright's selector cannot find.
            self.effort_marked = "setAttribute(P.attr, P.value)" in script
            # 2026-08-05: the script now reports WHAT it marked and what it refused,
            # so the caller can log a rejected sidebar link. `True` no longer
            # satisfies it — a double that kept returning a bare bool would make
            # `_eff_marked` read False and every Step 1C test fail for the wrong
            # reason. The real filtering is exercised against the DOM shim in
            # test_drift_review_0805.py; here the double only has to answer in the
            # right SHAPE.
            return {"marked": self.effort_marked, "text": "effort max",
                    "shows": self.effort_row_shows, "rejected": []}
        if _SUBMENU_ROWS_MARK in script:
            # 2026-08-04: the submenu now has to be SEEN, not assumed. Marking
            # the Effort row and pressing it is not evidence that a nested menu
            # mounted — the corpus says it usually did not — so the double has
            # to answer with the submenu's rows, and only once it has been
            # pressed. A double that answered before the press would agree with
            # exactly the code that failed nine times live.
            #
            # ⚠ 2026-08-17: the answer is now PER OVERLAY. The model popover is
            # always up (it holds the trigger); the submenu appears beside it
            # once pressed. Answering with a flat row list would let the shape
            # that shipped the bug pass here.
            popover = {"trigger": True, "option": False, "rungs": 0,
                       "labels": ["opus 5for complex tasks", "effortmax"]}
            if not self.presses:
                return {"overlays": [popover]}
            return {"overlays": [popover,
                                 {"trigger": False, "option": True, "rungs": 5,
                                  "labels": ["low", "medium", "highdefault",
                                             "extra", "max"]}]}
        if _THINKING_MARK in script:
            return {"found": True, "toggled": False}
        if _EFFORT_SET_MARK in script:
            # ⚠ 2026-08-17: a DICT, which is what production has read since the
            # picker started reporting which row it chose. The bare string used
            # to make `_eff_set.get(...)` raise straight into Step 1C's own
            # `except`, so these tests could only ever see that the script RAN.
            if not self.wanted_row:                  # the 09-20 page: no 'max' row
                return {"set": None, "scoped": True, "menus": 2, "cands": 1,
                        "saw": ["opus 5for complex tasks", "effortlow", "more models"]}
            if not self.wanted_already:              # there, but not selected: marked
                return {"set": "marked", "already": False, "via": "testid",
                        "picked": "max", "scoped": True, "menus": 2, "cands": 1}
            return {"set": "max (already)", "already": True, "via": "text",
                    "picked": "max", "scoped": True, "menus": 2, "cands": 1}
        if "cowork" in script.lower():
            return self.chat_tab
        if "aria-label" in script and "cand.click()" in script:
            return "plus"                     # the '+' tools-menu detector
        if "research" in script.lower():
            return self.research_on
        return None


def _run(page, **kw):
    return asyncio.run(research.setup_claude_dr(page, **kw))


@pytest.fixture(autouse=True)
def _isolated_overlay(monkeypatch, tmp_path):
    """⛔ The probe cadence PERSISTS. Without this every test that opens the
    popover would stamp the developer's real ~/.super-research/model_refresh.json
    and then silently change what the NEXT test sees."""
    monkeypatch.setattr(models, "_MODEL_REFRESH_OVERLAY_PATH",
                        tmp_path / "model_refresh.json")
    monkeypatch.setenv("DG_MODEL_REFRESH_ENABLED", "1")


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    """setup_claude_dr sleeps ~5s in fixed waits. Keep the ordering, drop the
    wall-clock — patched on the asyncio module research.py actually calls."""
    async def _instant(_secs):
        return None
    monkeypatch.setattr(research.asyncio, "sleep", _instant)


# ── the fix ───────────────────────────────────────────────────────────────

def test_popover_is_not_opened_when_the_trigger_already_shows_model_and_effort():
    """The reported bug. Trigger reads "Opus 5 Max": model is above the floor and
    effort is already Max, so there is nothing behind the popover to set."""
    page = ScriptedPage("Opus 5 Max")
    _run(page)
    assert page.evaluated(_TRIGGER_READ_MARK), "the trigger must still be read"
    assert not page.evaluated(_POPOVER_OPEN_MARK), (
        "the model popover was opened even though the trigger already showed a "
        "model above the floor AND the target effort — this is the duplicate "
        "model-menu interaction the fix removes"
    )
    # Nothing behind the popover ran either.
    assert not page.evaluated(_EFFORT_SUBMENU_MARK)
    assert not page.evaluated(_THINKING_MARK)


def test_research_tool_is_still_enabled_on_the_skip_path():
    """Skipping the popover must not skip the correctness gate. The Research tool
    lives in a different menu and is a hard requirement."""
    page = ScriptedPage("Opus 5 Max")
    assert _run(page) is True
    assert page.evaluated("cand.click()"), (
        "Step 3 must still open the tools menu and enable Research when Step 1A "
        "is skipped — the skip is about quality knobs, not the hard gate"
    )


# ── every fall-through path still opens it ────────────────────────────────

def test_popover_opens_when_the_trigger_shows_no_effort():
    """Effort unknown ⇒ not confirmed. The skip requires a POSITIVE read of both
    facts, so an effort-less trigger must behave exactly as before the fix."""
    page = ScriptedPage("Opus 5")
    _run(page)
    assert page.evaluated(_POPOVER_OPEN_MARK)
    assert page.evaluated(_EFFORT_SUBMENU_MARK), "the Effort submenu must still be reached"


def test_an_older_version_of_the_family_no_longer_forces_a_repick():
    """⭐ THE FAMILY-ONLY CHANGE, stated as behaviour. This used to open the
    popover because 4.7 was below a floor of 4.8. There is no floor now: an older
    member of the family is a correct model, and what gets it upgraded is the
    periodic probe (below), not a constant that ages out."""
    page = ScriptedPage("Opus 4.7 Max")
    _run(page)
    assert not page.evaluated(_POPOVER_OPEN_MARK), (
        "any member of the family counts as selected — comparing against a "
        "version here is what rots on every release"
    )


def test_popover_opens_when_the_trigger_has_no_model_at_all():
    """Sonnet/Haiku, or a layout the version regex misses: no version ⇒ the model
    is not confirmed ⇒ open the picker."""
    page = ScriptedPage("Sonnet 4.6")
    _run(page)
    assert page.evaluated(_POPOVER_OPEN_MARK)


def test_pin_model_still_forces_the_popover_open():
    """The Phoenix known-good fallback pins a specific version BECAUSE the higher
    one failed Deep-Research verification. A trigger reading higher-and-Max must
    NOT short-circuit that deliberate downgrade."""
    page = ScriptedPage("Opus 5 Max")
    _run(page, pin_model=4.8)
    assert page.evaluated(_POPOVER_OPEN_MARK), (
        "pin_model must always reach the picker — skipping it would silently "
        "keep the model that just failed verification"
    )
    assert page.evaluated(_PICK_OPUS_MARK)


def test_policy_thinking_true_reopens_the_popover(monkeypatch):
    """The skip is policy-driven, not hardcoded. If a future model reinstates a
    control that lives behind the popover, flipping one dict value must bring the
    popover back — including on a trigger that reads model AND effort."""
    monkeypatch.setitem(models.P2_MODEL_POLICY["claude"], "thinking", True)
    page = ScriptedPage("Opus 5 Max")
    _run(page)
    assert page.evaluated(_POPOVER_OPEN_MARK), (
        "with thinking re-enabled in policy there IS something behind the "
        "popover again, so it must open"
    )
    assert page.evaluated(_THINKING_MARK), "and the Thinking probe must run"


# ── the Effort submenu must actually open ─────────────────────────────────

def test_the_effort_row_is_hovered_and_pressed_for_real(monkeypatch):
    """⭐ The corpus, 2026-08: "Step 1C WARN: 'Max' effort not found in submenu"
    nine times against ONE success. The row was clicked from inside
    page.evaluate and the code took "an element was found" as proof the submenu
    had opened — so Max and the Thinking toggle were hunted inside a menu that
    was never there. A nested menu opens on the pointer ARRIVING on its parent
    row, which is why the hover is not a nicety."""
    monkeypatch.setitem(models.P2_MODEL_POLICY["claude"], "thinking", True)
    page = ScriptedPage("Opus 5 Max")
    _run(page)
    assert page.hovers, "the Effort row was never hovered"
    assert page.presses, "the Effort row was never pressed"
    assert all(s.startswith('[data-sr-click-target="claude-effort"')
               for s in page.hovers + page.presses), (page.hovers, page.presses)


def test_nothing_inside_the_submenu_is_touched_until_it_mounts(monkeypatch):
    """The whole defect in one assertion: with no submenu, the Max pick and the
    Thinking probe must not run at all. Before, both ran against the closed
    parent menu and each reported its own target missing — two misleading
    warnings from one unopened menu."""
    monkeypatch.setitem(models.P2_MODEL_POLICY["claude"], "thinking", True)

    class _NeverMounts(ScriptedPage):
        async def evaluate(self, script, arg=None):
            if _SUBMENU_ROWS_MARK in script:
                self.scripts.append(script)
                # Only the model popover is up — the overlay that HOLDS the
                # Effort trigger. Nothing else mounted.
                return {"overlays": [{"trigger": True, "option": False, "rungs": 0,
                     "labels": ["opus 5for complex tasks", "effortmax"]}]}
            return await ScriptedPage.evaluate(self, script, arg)

    page = _NeverMounts("Opus 5 Max")
    _run(page)
    assert page.presses, "it must still try"
    assert not page.evaluated(_THINKING_MARK), "the Thinking probe ran on a closed menu"
    assert not page.evaluated(_EFFORT_SET_MARK), "Max was picked from a closed menu"


def test_a_submenu_that_takes_a_moment_is_still_used(monkeypatch):
    """The read is a poll, not a single look after a fixed sleep."""
    monkeypatch.setitem(models.P2_MODEL_POLICY["claude"], "thinking", True)

    class _Slow(ScriptedPage):
        reads = 0

        async def evaluate(self, script, arg=None):
            if _SUBMENU_ROWS_MARK in script:
                self.scripts.append(script)
                _Slow.reads += 1
                if _Slow.reads < 3:
                    return {"overlays": [{"trigger": True, "option": False, "rungs": 0,
                     "labels": ["opus 5for complex tasks", "effortmax"]}]}
                return {"overlays": [{"trigger": True, "option": False, "rungs": 0,
                     "labels": ["opus 5for complex tasks", "effortmax"]},
                                    {"trigger": False, "option": True, "rungs": 5,
                     "labels": ["low", "medium", "highdefault", "extra", "max"]}]}
            return await ScriptedPage.evaluate(self, script, arg)

    page = _Slow("Opus 5 Max")
    _run(page)
    assert page.evaluated(_EFFORT_SET_MARK), "the submenu mounted late and was missed"


def test_an_unrecognised_overlay_still_reaches_the_row_picker(monkeypatch):
    """⭐⭐ 2026-08-17. The gate that shipped could VETO a picker that verifies its
    own work, and did: it reported "submenu never mounted" while its own
    diagnostic listed the submenu and all five rungs, so effort silently stayed
    at the model's default for the whole phase.

    An overlay that is not the model popover is up and nothing in it was
    recognised. That describes the page; it does not settle the run. Step 1C' is
    scoped to that same overlay and checks that the row became selected before
    claiming anything, so it is allowed to try."""
    monkeypatch.setitem(models.P2_MODEL_POLICY["claude"], "thinking", True)

    class _Unrecognised(ScriptedPage):
        async def evaluate(self, script, arg=None):
            if _SUBMENU_ROWS_MARK in script:
                self.scripts.append(script)
                return {"overlays": [
                    {"trigger": True, "option": False, "rungs": 0,
                     "labels": ["opus 5for complex tasks", "effortmax"]},
                    {"trigger": False, "option": False, "rungs": 0,
                     "labels": ["niedrig", "mittel", "hoch"]}]}
            return await ScriptedPage.evaluate(self, script, arg)

    page = _Unrecognised("Opus 5 Max")
    _run(page)
    assert page.evaluated(_EFFORT_SET_MARK), (
        "an unrecognised overlay must not veto the picker")
    assert not page.evaluated(_THINKING_MARK), (
        "but the Thinking search is page-wide and stays gated on a CONFIRMED "
        "submenu — widening the effort attempt must not widen an unscoped click")


# ── the thinking probe is gated, not deleted ──────────────────────────────

def test_thinking_probe_does_not_run_when_policy_says_the_toggle_is_gone():
    """Opus 5 has no Thinking toggle. Probing for it produced a WARN on every
    single healthy run, which is what made a working setup look broken."""
    page = ScriptedPage("Opus 5")          # forces the popover open via no-effort
    _run(page)
    assert page.evaluated(_EFFORT_SUBMENU_MARK), "the Effort submenu still opens (Max lives there)"
    assert not page.evaluated(_THINKING_MARK), (
        "the Thinking toggle must not be searched for when policy says the "
        "model family no longer has one"
    )


def test_policy_is_the_only_lever_for_thinking():
    """Guards against re-hardcoding: the decision must read the policy dict."""
    import inspect
    src = inspect.getsource(research.setup_claude_dr)
    assert "_claude_wants_thinking" in src
    assert 'p2_labels("claude")' in src, (
        "effort/thinking must come from the policy accessor, not literals"
    )


# ── the periodic model check (the other half of the fix) ──────────────────
# Skipping the popover is right. Skipping it FOREVER strands the account: the
# upgrade probe lives behind that popover, so with `model_ok` reduced to "the
# trigger names the family" a healthy run would never look at the menu again.

def test_a_due_probe_opens_the_popover_even_when_nothing_needs_setting():
    page = ScriptedPage("Opus 5 Max")
    _run(page, allow_probe=True)          # nothing learned yet ⇒ probe is due
    assert page.evaluated(_POPOVER_OPEN_MARK), (
        "with the periodic check due, the popover must open to look for a newer "
        "model — otherwise the account sits on its current one for good"
    )
    assert page.evaluated(_PROBE_MARK), "and the read-only probe must run"


def test_a_due_probe_upgrades_to_a_strictly_newer_model():
    page = ScriptedPage("Opus 5 Max", offered=6.0)
    _run(page, allow_probe=True)
    assert page.evaluated(_PICK_OPUS_MARK), "a newer model offered must be selected"


def test_a_due_probe_does_not_re_click_the_current_model():
    """#744 stays dead: the probe clicks only on a STRICTLY higher version."""
    page = ScriptedPage("Opus 5 Max", offered=5.0)
    _run(page, allow_probe=True)
    assert page.evaluated(_PROBE_MARK)
    assert not page.evaluated(_PICK_OPUS_MARK), (
        "nothing newer is offered, so the picker must not run at all"
    )


def test_the_probe_does_not_walk_into_the_effort_submenu():
    """The popover is open only to read the model list. Re-entering the Effort
    submenu when the trigger already showed the effort is the pointless churn the
    2026-07-30 change removed — and re-entering it is how the submenu gets left
    open under the composer."""
    page = ScriptedPage("Opus 5 Max")
    _run(page, allow_probe=True)
    assert not page.evaluated(_EFFORT_SUBMENU_MARK), (
        "effort was already confirmed off the trigger; opening its submenu adds "
        "nothing and risks stranding it open"
    )


def test_the_probe_still_dismisses_the_popover_twice():
    """#751: one Escape closes only an inner submenu. Any path that opened the
    popover must leave nothing over the composer."""
    page = ScriptedPage("Opus 5 Max")
    _run(page, allow_probe=True)
    assert [k for _, k in page.events].count("Escape") >= 2, (
        "a probe that opens the popover must close it, or the next step's "
        "'+' menu is sitting under an overlay"
    )


def test_the_probe_runs_once_per_interval_not_once_per_run():
    first = ScriptedPage("Opus 5 Max")
    _run(first, allow_probe=True)
    assert first.evaluated(_POPOVER_OPEN_MARK)
    second = ScriptedPage("Opus 5 Max")
    _run(second, allow_probe=True)        # same overlay ⇒ stamp is fresh
    assert not second.evaluated(_POPOVER_OPEN_MARK), (
        "the cadence must hold across runs — a probe every run IS the #744 "
        "complaint the skip was built to fix"
    )


def test_a_probe_that_never_sees_the_menu_still_burns_the_interval():
    """⭐ THE SAFETY PROPERTY. Stamping only on a successful read would leave the
    probe permanently due the moment the popover markup rotates — re-opening the
    model menu on EVERY run. One dead canary must not become a per-run
    regression."""
    broken = ScriptedPage("Opus 5 Max", menu_mounts=False)
    _run(broken, allow_probe=True)
    assert broken.evaluated(_POPOVER_OPEN_MARK)
    again = ScriptedPage("Opus 5 Max", menu_mounts=False)
    _run(again, allow_probe=True)
    assert not again.evaluated(_POPOVER_OPEN_MARK), (
        "a blind probe must still stamp the clock, or a rotated popover reopens "
        "on every single run forever"
    )


def test_the_probe_never_runs_when_the_kill_switch_is_off(monkeypatch):
    """⛔ THE INVERSION. Flag off ⇒ nothing is read or written ⇒ `last_probe` is
    permanently absent. A naive "no stamp means due" would make the OFF switch
    open the popover every run — the exact opposite of what OFF means."""
    monkeypatch.setenv("DG_MODEL_REFRESH_ENABLED", "0")
    for _ in range(3):
        page = ScriptedPage("Opus 5 Max")
        _run(page, allow_probe=True)
        assert not page.evaluated(_POPOVER_OPEN_MARK)


def test_recovery_re_runs_never_probe():
    """⛔ Only the INITIAL setup may probe. `setup_claude_dr` is also called by
    the pre-send re-activation, where an open model popover lands over the
    composer seconds before the brief is sent (the #744 screenshot)."""
    page = ScriptedPage("Opus 5 Max")
    _run(page)                             # no allow_probe → the default
    assert not page.evaluated(_POPOVER_OPEN_MARK)


def test_only_the_initial_p2_setup_passes_allow_probe():
    """Pins the call-site rule the test above depends on: exactly one caller
    opts in, and it is the LAYER-1 setup that runs before anything is typed.

    Scanned across the whole module rather than one function, because the
    dangerous callers are the recovery re-runs scattered through it — a new one
    added later must not quietly inherit the probe."""
    import inspect

    from conftest import code_only
    src = code_only(inspect.getsource(research))
    assert src.count("allow_probe=True") == 1, (
        "exactly one call site may enable the periodic probe — every other "
        "setup_claude_dr call runs with a live composer, where an open model "
        "popover lands over the message box (#744)"
    )
    # …and it is the Layer-1 initial setup — the only setup_claude_dr call whose
    # result becomes `setup_ok`. Every recovery re-run discards the return value,
    # which is what distinguishes them in code (the section headings that say so
    # are comments, and a comment cannot pin a call site).
    assert "setup_ok = await setup_claude_dr(page, allow_probe=True)" in src, (
        "the probing call must be the initial Layer-1 setup, not a recovery re-run"
    )
    assert "allow_probe" not in code_only(inspect.getsource(research.ensure_deep_mode_active)), (
        "the pre-send re-activation must never probe"
    )


def test_a_versionless_family_label_is_still_a_selected_model():
    """The endpoint of the naming trend this change responds to: the platform
    drops version numbers ("Opus Max"). A version-only read would call that "no
    model found" and re-pick on every run."""
    page = ScriptedPage("Opus Max")
    _run(page)
    assert not page.evaluated(_POPOVER_OPEN_MARK), (
        "a version-less family label must read as the family being selected"
    )


# ── the picker's own filters, now driven rather than grepped ──────────────
# Before the page double honoured pin/below/triggerText, inverting any of these
# comparisons inside the JS left every behavioural test green — the filters were
# covered only by source-substring assertions.

def test_a_step_back_takes_the_best_row_under_the_failed_version():
    page = ScriptedPage("Opus 6 Max", rows=[6.0, 5.0, 4.8])
    _run(page, step_below=6.0)
    assert page.picked() == 5.0, "the highest row strictly below the failure"


def test_a_step_back_never_re_picks_the_failed_version():
    page = ScriptedPage("Opus 6 Max", rows=[6.0])
    _run(page, step_below=6.0)
    assert page.picked() is None, (
        "nothing older is offered, so the picker must select nothing rather "
        "than re-clicking the model that just failed"
    )


def test_a_pin_selects_that_exact_version():
    page = ScriptedPage("Opus 6 Max", rows=[6.0, 5.0, 4.8])
    _run(page, pin_model=4.8, step_below=6.0)
    assert page.picked() == 4.8, "an exact known-good beats the generic step-back"


def test_a_retired_pin_still_steps_back_instead_of_giving_up():
    """⭐ THE REVIEW FINDING. A learned known-good never expires, so the platform
    may have retired it weeks later. Treating "pin absent" as "nothing to pick"
    threw away a usable older row and parked the leg."""
    page = ScriptedPage("Opus 6 Max", rows=[6.0, 5.0])   # 4.8 is gone
    _run(page, pin_model=4.8, step_below=6.0)
    assert page.picked() == 5.0, (
        "with the pinned version off the menu the picker must fall back to the "
        "best row strictly below the one that failed"
    )


def test_a_versionless_family_word_on_a_marketing_chip_is_not_a_selected_model():
    """⭐ FOUND IN REVIEW. Accepting a version-less family word page-wide is far
    too weak: on a Sonnet-only account a chip like "Opus — included in Max" or
    "Opus trial" would read as "the family is selected", so setup would skip the
    picker AND report success, and the run would go out on Sonnet. A NUMBERED
    label stays page-wide (long-standing behaviour, and strong evidence); only
    the new, weaker signal is scoped to an actual model control."""
    page = ScriptedPage("Opus Max", trigger_is_model_ctl=False)
    _run(page)
    assert page.evaluated(_POPOVER_OPEN_MARK), (
        "an unscoped family word must NOT satisfy the model check — the picker "
        "has to open and select a real model"
    )
    # ⚠ The scoping itself lives in the JS, and the page double models the
    # CONTRACT in Python — so the behavioural check above cannot see the JS
    # losing its guard. Pin the implementation too.
    from conftest import code_only_deep
    src = code_only_deep(research.setup_claude_dr)
    assert "isModelCtl" in src and "famRe.test(t) && isModelCtl(b)" in src, (
        "the version-less family read must be scoped to a model control"
    )


def test_the_periodic_upgrade_re_asserts_effort_on_the_new_model():
    """⭐ FOUND IN REVIEW. Claude stores effort PER MODEL. When the periodic
    check switches models, the effort read off the trigger described the OLD
    one — skipping the Effort submenu then leaves the newly-selected model on
    its default effort while telemetry reports effort confirmed. Effort is the
    reasoning lever on this family, so that is a silent quality downgrade for
    every run after the upgrade."""
    page = ScriptedPage("Opus 5 Max", offered=6.0, rows=[6.0, 5.0])
    _run(page, allow_probe=True)
    assert page.picked() == 6.0, "precondition: the probe upgraded the model"
    assert page.evaluated(_EFFORT_SUBMENU_MARK), (
        "after switching models the Effort submenu must be entered — the "
        "trigger's effort belonged to the model we just replaced"
    )


def test_a_probe_that_changes_nothing_still_skips_the_effort_submenu():
    """The other half: when the check finds nothing newer, the effort read off
    the trigger is still valid, so re-entering the submenu is the pointless
    churn the 2026-07-30 change removed."""
    page = ScriptedPage("Opus 5 Max", offered=5.0, rows=[5.0])
    _run(page, allow_probe=True)
    assert page.picked() is None, "precondition: nothing newer was offered"
    assert not page.evaluated(_EFFORT_SUBMENU_MARK)


def test_a_previous_runs_model_version_does_not_leak_into_the_next():
    """`_P2_PICKED_VERSION` is a process-global that outlives a run, and several
    paths return before writing it (Step 1A FAIL, Step 1B FAIL, the outer
    except). A stale entry is then read as "the version that just failed" by the
    step-back path, steering the retry off a number from another run."""
    research._P2_PICKED_VERSION["claude"] = 99.0
    # A run that bails BEFORE the write: no family on the trigger AND the
    # popover trigger button cannot be found, so Step 1A FAILs and setup returns
    # early. Only the clear-at-entry can remove the stale value here.
    page = ScriptedPage("Sonnet 4.6", popover_opens=False)
    assert _run(page) is False, "precondition: this run must bail before picking"
    assert "claude" not in research._P2_PICKED_VERSION, (
        "the stale value from a previous run must be cleared at ENTRY — every "
        "early return skips the write, so clearing at the end cannot work"
    )


# ── 2026-09-23: versions reach .10 — the REAL page scripts, the real gate ────
# The double above models the page's contract in Python, so it cannot see the
# page scripts reading "5.10" as 5.1. `RealMenuPage` runs the actual trigger
# read, offered-probe and picker through tests/_domshim.py against a menu, and
# lets `setup_claude_dr`'s own Step 1B* gate decide — the whole consumer, end to
# end. Everything else (Step 1C, the tools menu) stays scripted.

class RealMenuPage(ScriptedPage):
    def __init__(self, trigger_text, menu_rows, **kw):
        super().__init__(trigger_text, **kw)
        from _domshim import el
        self.spec = el("body", {}, "", [
            el("button", {"aria-label": "Model selector"}, trigger_text),
            el("div", {"role": "menu"}, "", [
                el("div", {"role": "menuitemradio"}, r) for r in menu_rows]),
        ])
        self.real_clicks = []       # what the REAL picker clicked

    async def evaluate(self, script, arg=None):
        if (_TRIGGER_READ_MARK in script or _PROBE_MARK in script
                or _PICK_OPUS_MARK in script):
            from _domshim import run_js
            self.scripts.append(script)
            out = run_js(self.spec, script, arg)
            if _PICK_OPUS_MARK in script:
                self.real_clicks += out["clicks"]
            return out["ret"]
        return await ScriptedPage.evaluate(self, script, arg)


_needs_node = pytest.mark.skipif(
    __import__("shutil").which("node") is None, reason="node runs the page scripts")


@_needs_node
def test_a_computer_already_on_5_10_is_not_moved_back_to_5_5():
    """⛔ THE MEASURED DOWNGRADE. With floats the trigger 'Opus 5.10 Max' read
    5.1, the probe of {5.5, 5.10} reported 5.5 as the highest, 5.5 > 5.1 fired
    Step 1B*, and the picker — pinned to 5.5 — clicked Opus 5.5. The log called
    that an UPGRADE, every probe interval, on the newest model there is."""
    page = RealMenuPage("Opus 5.10 Max",
                        ["Opus 5.5 For complex tasks", "Opus 5.10 For complex tasks"])
    _run(page, allow_probe=True)
    assert page.evaluated(_PROBE_MARK), "precondition: the periodic check ran"
    assert page.real_clicks == [], (
        f"the picker clicked {page.real_clicks} — an account on 5.10 was moved to "
        "an older model and the run logged it as an upgrade")
    assert not page.evaluated(_PICK_OPUS_MARK)


@_needs_node
def test_a_computer_on_5_9_is_upgraded_to_5_10_and_learns_5_10():
    """The other direction, through the same gate. With floats the probe's
    highest was max(5.9, 5.1) = 5.9, nothing looked newer, and the account sat
    on 5.9 through the whole 5.10 release. And what is learned is the TEXT: a
    numbers-only gate on the recorded pick would have thrown "5.10" away."""
    page = RealMenuPage("Opus 5.9 Max",
                        ["Opus 5.9 For complex tasks", "Opus 5.10 For complex tasks"])
    _run(page, allow_probe=True)
    assert page.real_clicks == ["Opus 5.10 For complex tasks"], (
        f"the upgrade clicked {page.real_clicks}")
    assert research._P2_PICKED_VERSION.get("claude") == "5.10"


def test_the_learned_version_is_the_one_the_picker_reported():
    """⚠ PREFER THE PICK, by version — not by type. The picker now reports TEXT;
    the old gate let only numbers through and fell back to re-reading the LABEL,
    which is the row's first 60 characters and need not carry the version at all
    (a row whose name sits after its description)."""
    page = ScriptedPage("Sonnet 4.6", rows=["5.10"],
                        row_label=lambda v: "For complex, multi-step work and long-form")
    _run(page)
    assert page.picked() == "5.10", "precondition: the picker selected 5.10"
    assert research._P2_PICKED_VERSION.get("claude") == "5.10", (
        f"learned {research._P2_PICKED_VERSION.get('claude')!r} — the version the "
        "picker actually clicked was thrown away")


# ── 2026-09-23: the run says which effort it actually got ─────────────────
# The 09-20 run: the trigger read "Opus 5 Low", the Effort row showed Low, the
# submenu had no 'max' row, and the run went out at Low with a log that said only
# "NOT confirmed". These drive the real coroutine and read what it SAYS.

def _speaking(monkeypatch):
    said = {"log": [], "events": []}
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: said["log"].append((level, msg)))
    monkeypatch.setattr(research, "emit_event",
                        lambda *a, **k: said["events"].append((a, k)))
    return said


def _captions(said):
    return [k.get("progress") for a, k in said["events"]
            if a and a[0] == "agent_progress" and k.get("agent") == "claude"]


def _ledger(said):
    return [m for _, m in said["log"] if "claude.select_effort_tier" in m]


def test_a_run_left_at_low_says_low(monkeypatch):
    said = _speaking(monkeypatch)
    page = ScriptedPage("Opus 5 Low", effort_row_shows="effort low", wanted_row=False)
    _run(page, allow_probe=True)
    assert any("effort in effect: 'low'" in m for _, m in said["log"]), said["log"]
    # Recorded for the pre-send check, which puts the caption on the tile once
    # the computer-use pass has had its turn (test_claude_real_popover_0923).
    assert _captions(said) == []
    assert research._P2_THINKING_STATE["claude"]["effort_got"] == "low"
    assert _ledger(said) and "tier is 'low'" in _ledger(said)[-1], _ledger(said)


def test_the_caption_is_never_said_from_setup(monkeypatch):
    """The pre-send re-activation and the step-back call this function too, and
    no call of it posts the caption: the computer-use pass that runs after the
    initial setup may still set the tier. The log still says it."""
    said = _speaking(monkeypatch)
    page = ScriptedPage("Opus 5 Low", effort_row_shows="effort low", wanted_row=False)
    _run(page)                                  # not the initial setup
    assert any("effort in effect: 'low'" in m for _, m in said["log"]), said["log"]
    assert _captions(said) == []


def test_a_press_that_did_not_verify_claims_no_tier(monkeypatch):
    """The Max row was there and a press landed, but it never read back as
    selected. The row was read BEFORE the press, so 'low' may be stale and 'max'
    is unproven: the run says unknown, and shows nothing."""
    said = _speaking(monkeypatch)
    page = ScriptedPage("Opus 5 Low", effort_row_shows="effort low",
                        wanted_row=True, wanted_already=False)
    _run(page, allow_probe=True)
    assert any("claude-effort-option" in p for p in page.presses), (
        "precondition: the Max row was pressed")
    assert any("effort in effect: unknown" in m for _, m in said["log"]), said["log"]
    assert _captions(said) == []
    assert research._P2_THINKING_STATE["claude"]["effort_got"] is None


def test_a_run_at_max_says_max_and_shows_nothing(monkeypatch):
    said = _speaking(monkeypatch)
    page = ScriptedPage("Opus 5 Max")           # read off the trigger
    _run(page, allow_probe=True)
    assert any("effort in effect: 'max'" in m for _, m in said["log"]), said["log"]
    assert _captions(said) == []
    assert research._P2_THINKING_STATE["claude"]["effort_got"] == "max"
