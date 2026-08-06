"""2026-08-05 prod incident — the pre-send DR check disagreed with setup.

Live run, backend v0.1.12, worker 1 (backend.log 682173-682198):

    [07:01:26] [setup_chatgpt_dr] Step 3 OK: verified DR active
                                  (pill='' placeholder='get a detailed report')
    [07:01:26] [dom] p2 chatgpt.setup_deep_research: verified ms=9503
    [07:01:32] [2A] ChatGPT Deep Research OFF before send (pillVisible=False)
    [07:01:34] [2A] ChatGPT DR post-re-activate: active=False
    [07:01:34] [2A] Deep Research unavailable after Layer 1 + Layer 2 + pre-send
                    re-activation — chat-mode gate (non-blocking)

Six seconds, one composer, two answers. ChatGPT stopped rendering the
Deep-Research pill in the composer, so the ONLY remaining active-DR signal is
the placeholder "Get a detailed report" — which contains 'report' but not
'research'. `_CHATGPT_DR_ACTIVE_JS` had already been taught that (its regex is
/detailed report|deep research|research report/) and setup_chatgpt_dr's Step 3
verifies with it. `ensure_deep_mode_active` carried a PRIVATE copy that still
tested `placeholder.includes('research')` and demanded the pill text be exactly
'deep research'.

So the gate could never clear itself: the re-activation reads the placeholder,
concludes "ALREADY active", declines to click — and the next line reports
active=False. Every ChatGPT P2 leg on that build raised a chat-mode alert.

The rule these tests pin is the one Step 3's own comment already states: one
question gets ONE predicate. The migration to the shared detector reached five
call sites and missed this one; a presence assertion alone would not have
caught that, so the behavioural tests below run the real predicate against the
real composer shape.

Run:  pytest tests/test_chatgpt_dr_one_predicate.py -v
"""
import inspect
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research
from _domshim import NODE, el, run_js
from conftest import code_only_deep

ENSURE_SRC = code_only_deep(research.ensure_deep_mode_active)


def _chatgpt_branch() -> str:
    """Just the ChatGPT arm of ensure_deep_mode_active, comments stripped."""
    i0 = ENSURE_SRC.index('if platform_l == "chatgpt":')
    i1 = ENSURE_SRC.index('if platform_l == "gemini":')
    assert i0 < i1
    return ENSURE_SRC[i0:i1]


# ── The composer shape that actually shipped ──────────────────────────────

def _composer(*, pill: str = "", placeholder: str = "Get a detailed report"):
    """The live P2 composer: a form, a textarea carrying the placeholder, and
    (by default) NO Deep-Research pill — which is what ChatGPT renders now."""
    kids = []
    if pill:
        kids.append(el("button", {"class": "__composer-pill"}, pill))
    kids.append(el("textarea", {"id": "prompt-textarea",
                                "placeholder": placeholder}, ""))
    return el("body", {}, "", [el("form", {}, "", kids)])


needs_node = pytest.mark.skipif(NODE is None, reason="node required to run page JS")


@needs_node
def test_the_shipped_composer_reads_as_active():
    """The exact state of the incident: pill='' placeholder='get a detailed
    report'. This is the assertion the private copy failed."""
    out = run_js(_composer(), research._CHATGPT_DR_ACTIVE_JS)["ret"]
    assert out["active"] is True, (
        f"the live Deep-Research composer reads as OFF: {out!r}"
    )
    assert out["pillText"] == "", "fixture must have no pill — that is the point"
    assert "detailed report" in out["placeholder"]


@needs_node
def test_the_old_private_predicate_would_have_failed_this_composer():
    """Not a tautology check — this pins WHY the two disagreed, so a future
    edit that reinstates an `includes('research')` style test has a failing
    test naming the reason rather than a silent behaviour change."""
    superseded = """() => {
        const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
        const form = document.querySelector('form') || document.body;
        let pillVisible = false;
        for (const p of form.querySelectorAll('button, [role="button"], span, div')) {
            if (!p.offsetParent) continue;
            const t = norm(p.textContent);
            if (t === 'deep research') { pillVisible = true; break; }
        }
        let placeholder = '';
        const ta = document.querySelector('#prompt-textarea, textarea, [contenteditable="true"]');
        if (ta) placeholder = norm(ta.getAttribute('placeholder') || ta.getAttribute('data-placeholder'));
        return { active: pillVisible || placeholder.includes('research') };
    }"""
    old = run_js(_composer(), superseded)["ret"]
    new = run_js(_composer(), research._CHATGPT_DR_ACTIVE_JS)["ret"]
    assert old["active"] is False and new["active"] is True, (
        "the superseded predicate no longer disagrees with the shared one — if "
        "ChatGPT's placeholder changed, update the fixture, not this assertion"
    )


@needs_node
@pytest.mark.parametrize("pill,placeholder", [
    ("Deep research", "Get a detailed report"),   # both signals
    ("Deep research", "Ask anything"),            # pill only
    ("", "Get a detailed report"),                # placeholder only (shipped)
    ("Deep research beta", "Ask anything"),       # pill with a suffix
])
def test_every_way_deep_research_announces_itself_reads_as_active(pill, placeholder):
    out = run_js(_composer(pill=pill, placeholder=placeholder),
                 research._CHATGPT_DR_ACTIVE_JS)["ret"]
    assert out["active"] is True, f"{pill!r}/{placeholder!r} read as OFF: {out!r}"


@needs_node
def test_a_plain_composer_still_reads_as_off():
    """The detector must keep a real negative. An escape hatch that always says
    'on' would hide a genuine chat-mode degradation, which is the whole reason
    the gate exists (#709)."""
    out = run_js(_composer(placeholder="Ask anything"),
                 research._CHATGPT_DR_ACTIVE_JS)["ret"]
    assert out["active"] is False, f"a chat-mode composer read as ON: {out!r}"


@needs_node
def test_a_sent_message_badge_outside_the_form_cannot_fake_it():
    """Scoping to `form` is load-bearing: an already-SENT message carries a
    'Deep research' badge, and treating that as composer state would make the
    gate unfalsifiable after the first send."""
    spec = el("body", {}, "", [
        el("div", {}, "", [el("span", {}, "Deep research")]),          # sent bubble
        el("form", {}, "", [el("textarea", {"id": "prompt-textarea",
                                            "placeholder": "Ask anything"}, "")]),
    ])
    out = run_js(spec, research._CHATGPT_DR_ACTIVE_JS)["ret"]
    assert out["active"] is False, f"a sent-message badge leaked in: {out!r}"


# ── One question, one predicate ───────────────────────────────────────────

def test_the_presend_check_evaluates_the_shared_detector():
    branch = _chatgpt_branch()
    assert "_CHATGPT_DR_ACTIVE_JS" in branch, (
        "the pre-send check must evaluate the shared detector, not its own read"
    )
    # Both reads — the first measurement AND the post-re-activation one. The
    # incident needed only ONE of them to drift to produce the contradiction.
    assert branch.count("page.evaluate(_CHATGPT_DR_ACTIVE_JS)") >= 2, (
        "the post-re-activate read must use the shared detector too"
    )


def test_the_presend_check_defines_no_predicate_of_its_own():
    """The regression was a second predicate, not a wrong one. Ban the shape."""
    branch = _chatgpt_branch()
    assert "_cgpt_state_js" not in branch, "the private copy is back"
    assert "querySelectorAll" not in branch and "offsetParent" not in branch, (
        "the ChatGPT branch is reading the DOM directly again — route the "
        "question through the shared detector instead"
    )
    assert "includes('research')" not in branch, (
        "an includes('research') test cannot see the real Deep-Research "
        "placeholder 'Get a detailed report'"
    )


def test_only_one_chatgpt_dr_predicate_exists_module_wide():
    """The sweep that should have caught this. Any module-level JS constant
    answering 'is ChatGPT Deep Research on?' other than the shared one is a
    duplicate waiting to drift."""
    src = code_only_deep(inspect.getsource(research))
    # A DR-active predicate is recognisable: it tests the composer placeholder
    # for the Deep-Research wording.
    hits = re.findall(r"detailed report\|deep research\|research report", src)
    assert len(hits) == 1, (
        f"expected exactly one Deep-Research placeholder predicate, found "
        f"{len(hits)} — a second one will drift from the first, which is "
        f"precisely the 2026-08-05 incident"
    )


def test_setup_step_three_and_the_presend_check_share_the_predicate():
    """The two signals that disagreed in prod. Pin that they now come from the
    same constant, so 'verified' and 'off' cannot describe the same composer."""
    setup = code_only_deep(research.setup_chatgpt_dr)
    assert "_CHATGPT_DR_ACTIVE_JS" in setup or "_dr_state()" in setup
    # setup_chatgpt_dr reaches it through its _dr_state() helper.
    assert "_CHATGPT_DR_ACTIVE_JS" in code_only_deep(inspect.getsource(research))
    assert "_CHATGPT_DR_ACTIVE_JS" in _chatgpt_branch()


def test_the_off_log_line_reports_the_signal_that_actually_decides():
    """The prod line said `pillVisible=False` — describing a healthy composer,
    because an absent pill is now normal. The placeholder is what decides, so
    the diagnostic has to carry it or the next incident is unreadable again."""
    branch = _chatgpt_branch()
    off_log = branch[branch.index("Deep Research OFF before send"):]
    off_log = off_log[:off_log.index("setup_chatgpt_dr(page)")]
    assert "placeholder" in off_log, (
        "the OFF diagnostic omits the placeholder — the one signal that "
        "distinguishes 'chat mode' from 'pill simply not rendered'"
    )
