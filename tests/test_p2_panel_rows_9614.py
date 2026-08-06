"""DGOPS-9614 — the P2 activity panel's counts froze because nothing could match.

SETTLED FROM THE CAPTURE, not guessed. `~/.super-research/logs/p2_panel_dump_1.html`
(13957 chars, `section[aria-label="Reasoning details" data-testid="screen-threadFlyOut"]`)
contains:

    <li>              0
    role="listitem"   0
    h1/h2/h3          0
    class *step*      0
    class *activity*  0
    class *task*      0
    class *checklist* 0

…so every selector in the walker's STEP_SELS matched nothing, and it had reported
0 steps since it shipped. Meanwhile the panel's own innerText carried four:

    Activity · 3m 6s
    Pro thinking
    Searching 1 website
    docs.nvidia.com / www.nvidia.com / developer.nvidia.com
    14 more                          ← 14 sources we never counted
    Clarifying research scope        ← step 1
    I'm framing the report around …  ← step 1's body
    Designing the research brief     ← step 2
    …

The fingerprint MOVING while the counts froze is what ruled out the other candidate
cause (re-reading a detached node), and this file pins the fix against the real row
shape rather than against a selector we hoped for.

Everything here EXECUTES the production JS through the node DOM shim. The fixture
reproduces the captured markup verbatim, including the geometry the panel's root
finder needs — the walker locates this panel only via its "Activity" header, because
the panel is a <section> whose aria-label is "Reasoning details" and PANEL_SELS
matches none of that.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402
from _domshim import el, js_constant, run_js  # noqa: E402

WALKER_JS = js_constant(research.scrape_chatgpt_activity_panel_tracking, "JS")

# The four step titles the live panel showed while the walker reported none.
LIVE_STEPS = [
    "Clarifying research scope",
    "Designing the research brief",
    "Clarifying research direction",
    "Building the research brief",
]
LIVE_BODY = ("I’m framing the report around a key distinction: these names may "
             "refer to different layers, models, deployments or runtimes.")


def _step_row(title, body):
    """The captured row, verbatim from p2_panel_dump_1.html.

    Note what carries the title: a class-less-for-our-purposes
    `div.text-token-text-primary.text-[14px]` with the text as its only child. No
    role, no testid, no "step"/"activity" in any class — which is the whole ticket.
    """
    return el("div", {"class": "relative flex w-full items-start gap-2 overflow-clip"},
              kids=[
        el("div", {"class": "flex h-full w-4 shrink-0 flex-col items-center"}, kids=[
            el("div", {"class": "flex h-5 shrink-0 items-center justify-center"}, kids=[
                el("div", {"class": "bg-token-interactive-icon-tertiary-default "
                                    "h-[6px] w-[6px] rounded-full"})])]),
        el("div", {"class": "w-full min-w-0"}, kids=[
            el("div", {"class": "w-full min-w-0"}, kids=[
                el("div", {"class": "text-token-text-primary text-[14px]"}, title)]),
            el("div", {"class": "QKycbG_markdown text-token-text-secondary text-[14px]"},
               kids=[el("p", {}, body)])])])


def _panel(*, steps=LIVE_STEPS, hosts=3, more="14 more",
           search_chip="Searching 1 website", extra=(), prefix=()):
    """`prefix` goes BEFORE the step rows, `extra` after.

    ⚠ The distinction is load-bearing for the node-bound tests below. This panel
    APPENDS its steps — that is the premise of the trailing bound in `takeStep`, of
    `slice(-15)` and of `progress = steps[last]` alike — so filler that models panel
    chrome has to sit ahead of them. Padding placed after the steps makes them the
    OLDEST nodes, and then a tail window dropping them is correct behaviour rather
    than the defect.
    """
    kids = [
        # The header the root finder anchors on. Geometry matters: it must sit right
        # of half the viewport, and an ancestor must be panel-sized.
        el("div", {"class": "flex items-center justify-between px-4 py-3",
                   "x": "900", "y": "10"}, kids=[
            el("span", {"class": "min-w-0 truncate max-w-[220px]",
                        "x": "900", "y": "10", "w": "80", "h": "20"}, "Activity"),
            el("span", {"class": "text-token-text-tertiary shrink-0",
                        "x": "985", "y": "10"}, " · "),
            el("span", {"class": "text-token-text-tertiary shrink-0",
                        "x": "1000", "y": "10"}, "3m 6s")]),
        el("div", {"x": "900", "y": "40"}, "Pro thinking"),
    ]
    if search_chip:
        kids.append(el("div", {"x": "900", "y": "60"}, search_chip))
    # ⚠ 2026-08-06 — the source links and the "N more" chip share ONE ROW
    # container, because that is what the real captured panel does. This fixture
    # used to hang them as flat siblings of the section, and that structure is the
    # reason the count logic here was modelled as panel-wide: measured against
    # `tests/fixtures/panels/`, the chip's container holds exactly 3 links in two
    # captures of the same panel taken eight minutes apart, while the panel's own
    # total went from 3 to 40. The remainder belongs to its row, and a flat fixture
    # cannot express that.
    _row = el("div", {"class": "sources-row", "x": "900", "y": "80"}, kids=[
        el("a", {"href": f"https://host{i}.example.com/nemoclaw/page",
                 "x": "900", "y": str(80 + i * 20)}, f"host{i}.example.com")
        for i in range(hosts)])
    if hosts:
        kids.append(_row)
    if more:
        # Inside the row with its own links — see the note above.
        _row["kids"].append(el("div", {"x": "900", "y": "150"}, more))
        if not hosts:
            kids.append(_row)
    kids.extend(prefix)
    for t in steps:
        kids.append(_step_row(t, LIVE_BODY))
    kids.extend(extra)
    return el("body", kids=[
        el("section", {"aria-label": "Reasoning details",
                       "class": "_56rfYG_screen h-[var(--screen-height-override,",
                       "data-testid": "screen-threadFlyOut",
                       "w": "560", "h": "800", "x": "880", "y": "0"}, kids=kids)])


def _walk(spec):
    return run_js(spec, WALKER_JS)["ret"]


# ─────────────────────────────────────────────────────────────────────────────
# The ticket: the rows exist and were not being read.
# ─────────────────────────────────────────────────────────────────────────────

def test_the_old_selector_set_matches_nothing_on_the_live_panel():
    """The measurement that settles DGOPS-9614, asserted rather than asserted-about.

    If this ever starts matching, the structural pass below is no longer carrying the
    walker and the next person should know that before changing anything.
    """
    sels = ('li, [role="listitem"], [class*="step" i], [class*="checklist" i] > div, '
            '[class*="task" i] > div, [class*="activity" i]')
    out = run_js(_panel(), "(P) => document.querySelectorAll(P.sel).length",
                 {"sel": sels})["ret"]
    assert out == 0, (
        f"STEP_SELS matched {out} element(s) on the captured panel — the premise of "
        f"this ticket was that it matched none")


def test_the_four_live_step_titles_are_found():
    """Was 0 for the whole run. These are the exact titles from the capture."""
    got = _walk(_panel())
    assert got["steps"] == LIVE_STEPS, json.dumps(got.get("steps"), indent=2)


def test_the_progress_line_is_the_latest_step():
    got = _walk(_panel())
    assert got["progress"] == LIVE_STEPS[-1], got.get("progress")


def test_the_step_body_is_not_mistaken_for_a_step():
    """The gerund gate is the discriminator that already existed, and it still is:
    the body starts "I'm framing", the title starts "Clarifying"."""
    got = _walk(_panel())
    assert LIVE_BODY[:30] not in " | ".join(got["steps"])
    for s in got["steps"]:
        assert not s.startswith("I’m"), s


def test_the_source_count_chip_is_not_a_step():
    """"Searching 1 website" is a gerund and would pass the gate — and its NUMBER
    changes every poll, so each value would become a separate step and churn the
    list. It is already reported as `searches`."""
    got = _walk(_panel())
    assert not any("Searching" in s for s in got["steps"]), got["steps"]
    # …and it is not the gerund gate doing this: prove a non-count gerund of the
    # same shape IS taken.
    got2 = _walk(_panel(search_chip="Searching for primary sources"))
    assert "Searching for primary sources" in got2["steps"], got2["steps"]


def test_the_panel_header_is_not_a_step():
    got = _walk(_panel())
    for s in got["steps"]:
        assert "Activity" not in s and "3m 6s" not in s, s


def test_a_wrapper_that_holds_many_rows_is_not_itself_a_step():
    """The leaf rule. Without it the row's own grandparent — whose innerText is every
    title concatenated — would be a candidate, and one giant pseudo-step would replace
    the four real ones."""
    got = _walk(_panel())
    for s in got["steps"]:
        assert s.count("research") <= 1, f"a wrapper leaked in as one step: {s!r}"
    assert len(got["steps"]) == 4


def test_the_step_list_stays_bounded_on_a_huge_panel():
    """The rich state measured 26410 chars. A cap keeps one poll from shipping
    hundreds of rows to the frontend."""
    many = [f"Reviewing source number {i} of the corpus" for i in range(200)]
    got = _walk(_panel(steps=many))
    assert len(got["steps"]) <= 15, len(got["steps"])
    # …and it keeps the LATEST, which is what a progress line is for.
    assert got["steps"][-1] == many[-1]


# ─────────────────────────────────────────────────────────────────────────────
# f13e — the NODE bound must drop the oldest rows, not the newest.
# ─────────────────────────────────────────────────────────────────────────────

def _padding(n):
    """`n` leaf nodes that carry no step text — filler ahead of the real rows.

    Deliberately gerund-free and short, so the only thing they consume is the scan's
    NODE budget. That is the resource the bug was about.
    """
    return [el("span", {}, f"chrome {i}") for i in range(n)]


def test_the_node_bound_keeps_the_newest_rows_not_the_oldest():
    """⭐ The finding, reproduced before it was fixed: a panel with more than 6,000
    leaf nodes returned `steps == ['Clarifying research scope']` and froze `progress`
    on the OLDEST title, because the scan truncated in DOCUMENT order while this panel
    APPENDS. That is DGOPS-9614's own symptom, one panel size larger.

    The observed rich panel is ~4,613 elements against a 6,000 bound — a 30% margin,
    which is one busier run away.
    """
    got = _walk(_panel(prefix=_padding(7000)))
    assert got["steps"], "the newest rows were dropped by the node bound"
    assert got["steps"][-1] == LIVE_STEPS[-1], got["steps"]
    assert got["progress"] == LIVE_STEPS[-1], got["progress"]


def test_the_node_bound_still_bounds():
    """The other half. A window over the tail must not become an unbounded scan — the
    bound exists so a pathological DOM cannot stall a 30-second poll."""
    js = WALKER_JS
    assert "_leaves.length - 6000" in js, js[:0]
    # And the walk is FORWARD over that window: walking backwards would hand takeStep
    # newest-first, so `slice(-15)` would keep the fifteen oldest.
    win = js[js.index("const _leaves ="):js.index("out.steps = out.steps.slice(-15)")]
    assert "i++" in win, win
    assert "i--" not in win, win


def test_a_panel_under_the_bound_is_unaffected():
    """No behaviour change on every panel anyone has actually captured."""
    got = _walk(_panel(prefix=_padding(100)))
    assert [s for s in got["steps"]] == LIVE_STEPS


def test_padding_alone_produces_no_steps():
    """Guards the fixture, not the code: if the filler could pass the gerund gate the
    test above would prove nothing about which rows survived."""
    got = _walk(_panel(steps=[], prefix=_padding(7000)))
    assert got["steps"] == []


def test_the_bound_is_measured_in_nodes_so_the_step_count_alone_cannot_trip_it():
    """200 real step rows are ~1,400 nodes, well inside the window — so the earlier
    "stays bounded" test was never exercising the node bound at all. Stated here so the
    two tests are not mistaken for each other."""
    many = [f"Reviewing source number {i} of the corpus" for i in range(200)]
    got = _walk(_panel(steps=many))
    assert got["steps"][-1] == many[-1]


# ─────────────────────────────────────────────────────────────────────────────
# The collapsed source chip: 17 sources read as 1.
# ─────────────────────────────────────────────────────────────────────────────

def test_the_collapsed_more_chip_is_counted():
    """The panel showed 3 hosts and "14 more" and the walker reported `searches=1`
    for the entire phase — the frozen 1 is much of what made the panel look dead."""
    got = _walk(_panel(hosts=3, more="14 more"))
    assert got["searches"] == 17, got["searches"]


def test_the_more_chip_is_a_remainder_not_a_total():
    """Taking the max of (visible, more) would under-report by exactly the number of
    hosts on screen — which is the bug in miniature."""
    assert _walk(_panel(hosts=5, more="2 more"))["searches"] == 7


def test_an_explicit_count_still_wins_when_it_is_larger():
    """The original heuristic must survive: ChatGPT also renders "193 searches"."""
    got = _walk(_panel(hosts=3, more="14 more",
                       search_chip="Searching 193 websites"))
    assert got["searches"] == 193, got["searches"]


def test_with_no_more_chip_the_links_we_can_see_beat_a_smaller_stated_count():
    """⚠ 2026-08-06 — this test previously required `searches == 1` here: the panel
    renders three source links and says "Searching 1 website", and the stated word
    was trusted over the evidence on screen.

    That is the under-report this ticket exists for, in miniature. Three links are
    present and enumerable, so three is the honest floor — and it is the number a
    user gets if they open the source list, which a count of 1 would contradict.

    The test's real intent survives: the figure must not exceed what there is
    evidence for. With no remainder chip there is nothing hidden to add, so it
    stops at the three links rather than inventing a fourth.
    """
    got = _walk(_panel(hosts=3, more="", search_chip="Searching 1 website"))
    assert got["searches"] == 3, got["searches"]
    assert got["dbg_more_remainder"] == 0


def test_a_stated_count_larger_than_the_links_is_still_believed():
    """The complement, so the change above cannot be read as "always ignore the
    words": when the panel claims MORE than it has rendered, it is believed."""
    got = _walk(_panel(hosts=3, more="", search_chip="Searching 40 websites"))
    assert got["searches"] == 40, got["searches"]


def test_the_visible_sources_are_still_collected():
    got = _walk(_panel(hosts=3))
    assert len(got["source_urls"]) == 3, got["source_urls"]


# ─────────────────────────────────────────────────────────────────────────────
# Honest non-finding, recorded so it is not "fixed" blind.
# ─────────────────────────────────────────────────────────────────────────────

def test_sections_is_empty_on_this_panel_and_that_is_correct():
    """`sections` was 0 on every sample of the 11:08 run, and the capture explains it
    without a defect: the flyout contains no h1/h2/h3 at all. The walker must not
    invent headings to make the number look better — if a later capture shows the
    rich state DOES carry headings, that is when this changes, from evidence.
    """
    got = _walk(_panel())
    assert got["sections"] == []
    hs = run_js(_panel(), "() => document.querySelectorAll('h1, h2, h3').length")["ret"]
    assert hs == 0, "the fixture gained a heading — re-read the capture before editing"


def test_a_heading_in_the_panel_is_still_reported():
    """…and the heading path is not dead code: give the panel an h2 and it appears."""
    got = _walk(_panel(extra=(el("h2", {"x": "900", "y": "700"}, "Findings"),)))
    assert got["sections"] == ["Findings"], got["sections"]


# ─────────────────────────────────────────────────────────────────────────────
# The dump budget that cost DGOPS-9614 a second run.
# ─────────────────────────────────────────────────────────────────────────────

def _replay_dump_budget(textlens, monkeypatch, tmp_path):
    """Drive the REAL dump-budget block over a sequence of panel sizes.

    Executed, not read. The first attempt at this fix (cap 2 → 4 plus a growth
    trigger) passed every source-shape assertion and still failed on the real log,
    because the early panel repeats five times and identical-sample dumps had no
    cooldown. Only a replay catches that.

    Returns the list of textlens that actually got dumped.
    """
    monkeypatch.setattr(research, "_p2_panel_dbg_dumps", 0, raising=False)
    monkeypatch.setattr(research, "_p2_panel_last_fp", None, raising=False)
    monkeypatch.setattr(research, "_p2_panel_dbg_last_len", 0, raising=False)
    monkeypatch.setattr(research, "_p2_panel_dbg_frozen_done", False, raising=False)
    monkeypatch.setattr(research.os.path, "expanduser", lambda p: str(tmp_path))

    dumped = []
    real_open = open

    def _open(path, *a, **kw):
        if "p2_panel_dump_" in str(path):
            dumped.append(_current[0])
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", _open)
    _current = [0]

    for tl in textlens:
        _current[0] = tl
        # The walker's own fingerprint shape; a same-size sample is an identical one.
        res = {"source_urls": [], "steps": [], "sections": [], "searches": 0,
               "dbg_html": "<section>" + "x" * 10 + "</section>",
               "dbg_fp": {"tag": "SECTION|_56rfYG_screen", "kids": 3,
                          "textlen": tl, "anchors": 3, "rows": 0}}
        research._p2_panel_dbg_record(res)
    return dumped


def test_the_dump_budget_survives_the_real_log_sequence(monkeypatch, tmp_path):
    """⭐ The exact recorded sequence. backend.log 665308-665927 holds FIVE consecutive
    1254-char samples (10:52:20 → 10:56:25) and only then the rich 26410-char state
    from 11:00:51. Under the first fix all four slots went to 1254 and the state the
    ticket needed was missed for a second run.
    """
    seq = [664, 1254, 1254, 1254, 1254, 1254, 26410, 26410, 26410]
    dumped = _replay_dump_budget(seq, monkeypatch, tmp_path)
    assert 26410 in dumped, (
        f"the rich panel must be captured; dumped {dumped}")
    assert dumped.count(1254) <= 1, (
        f"the repeating early panel may spend at most one slot; dumped {dumped}")
    assert len(dumped) <= 4, dumped


def test_a_frozen_panel_still_gets_its_evidence_and_leaves_budget(monkeypatch, tmp_path):
    """The identical-sample evidence is the other half of the ticket — a panel that
    never changes must still produce an artifact.

    Two dumps here, and both are distinct evidence: the first sizeable panel (growth
    from nothing) and the first repeated sample. What must NOT happen is the repeat
    firing again and again — that is what spent the whole budget on the early state.
    """
    dumped = _replay_dump_budget([5000] * 8, monkeypatch, tmp_path)
    assert len(dumped) == 2, dumped
    assert dumped == [5000, 5000]
    # …and two slots remain for a later, larger panel.
    assert len(dumped) < 4


def test_growth_alone_is_enough_to_dump(monkeypatch, tmp_path):
    """A steadily growing panel never repeats a sample, so the frozen trigger never
    fires — growth has to carry it on its own."""
    dumped = _replay_dump_budget([2000, 4000, 9000, 30000], monkeypatch, tmp_path)
    assert len(dumped) >= 3, dumped
    assert 30000 in dumped, dumped


def test_a_slowly_growing_panel_does_not_exhaust_the_budget(monkeypatch, tmp_path):
    """The threshold is a real jump, not any change: 1.8× against a high-water mark."""
    dumped = _replay_dump_budget([2000, 2100, 2200, 2300, 2400, 2500],
                                 monkeypatch, tmp_path)
    assert len(dumped) <= 2, dumped


def test_the_growth_threshold_needs_a_real_jump():
    """A trigger that fires on any change would spend the budget on the first four
    polls, which is the failure it replaces."""
    from conftest import code_only_deep  # type: ignore
    src = code_only_deep(research._p2_panel_dbg_record)
    grew = src[src.index("_grew ="):src.index("\n", src.index("_grew ="))]
    assert "max(" in grew and "1.8" in grew, grew
    assert "False" not in grew and "True" not in grew, grew


# ─────────────────────────────────────────────────────────────────────────────
# Shim fidelity. These three gaps each made a passing test into no test at all.
# ─────────────────────────────────────────────────────────────────────────────

def test_the_shim_climbs_with_parentElement_like_a_browser():
    """Production climbs to a panel-sized ancestor with `el.parentElement`. The shim
    only exposed `parent`, so the climb hit `undefined` after one step, `activityRoot`
    came back null, and this whole walker returned zeros against a full fixture."""
    out = run_js(el("body", kids=[el("div", {"id": "a"}, kids=[
        el("span", {"id": "b"}, "x")])]),
        "() => { const s = document.querySelector('#b');"
        " return s.parentElement ? s.parentElement.getAttribute('id') : null; }")["ret"]
    assert out == "a"


def test_the_shim_exposes_href_as_a_resolved_property():
    """Production reads `a.href`, not `getAttribute('href')`. Undefined there meant
    every source-URL walk collected nothing from a fixture full of anchors."""
    out = run_js(el("body", kids=[el("a", {"href": "https://x.example/y"}, "x")]),
                 "() => document.querySelector('a').href")["ret"]
    assert out == "https://x.example/y"


def test_the_shim_innerText_is_line_aware_but_textContent_is_not():
    """`innerText` inserts line breaks between block elements in a browser and
    `textContent` does not. The shim returned the concatenation for both, which
    disarmed every production regex anchored on a word boundary — measured on the
    source-count regex, which could not match "1 website" glued to "docs.nvidia.com".
    """
    spec = el("body", kids=[el("div", {}, kids=[
        el("div", {}, "Searching 1 website"),
        el("div", {}, "docs.nvidia.com")])])
    out = run_js(spec, "() => ({ it: document.querySelector('div').innerText,"
                       " tc: document.querySelector('div').textContent })")["ret"]
    assert "1 website" in out["it"]
    assert "websitedocs" not in out["it"], out["it"]
    # textContent keeps browser semantics: no separators.
    assert "websitedocs" in out["tc"], out["tc"]
    # And the boundary the regex needs now exists.
    import re
    assert re.search(r"(\d+)\s+websites?\b", out["it"])
    assert not re.search(r"(\d+)\s+websites?\b", out["tc"])


def test_the_shim_reports_childElementCount():
    """The leaf test the structural pass uses. `undefined !== 0` is true for every
    node, so without this the pass would have rejected everything."""
    out = run_js(el("body", kids=[
        el("div", {"id": "leaf"}, "x"),
        el("div", {"id": "branch"}, kids=[el("span", {}, "y")])]),
        "() => ({ leaf: document.querySelector('#leaf').childElementCount,"
        " branch: document.querySelector('#branch').childElementCount })")["ret"]
    assert out == {"leaf": 0, "branch": 1}
