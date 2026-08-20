"""P1's activity drawer: the verifier could not see the shape it verified. 2026-08-19.

⛔⛔ THE DEFECT, and it cost four minutes of clicking the user's UI shut.
ChatGPT's P1 (Pro + Extended Thinking) UI has no activity side panel any more.
The shimmering line expands an INLINE ROW OF WEBSITE CHIPS — favicon plus bare
domain — directly beneath itself. `_chatgpt_activity_state` had exactly two ways
to say "open": a right-side panel, or `inline_expanded`, whose gates demand a
≥60px-tall, ≥120px-wide region of ≥40 characters whose class or testid names
"thought" or "activity". The measured chips are `class="flex"` and a hostname
long. So the predicate was false against an already-open drawer, and BOTH callers
believed it:

  02:59:01  CUA opens the chip row               → _panel_open_done = True
  02:59:32  "activity drawer collapsed — will re-open (reopen #1/3)"
  02:59:34 … 03:03:22  EIGHT presses of a TOGGLE

CUA narrated us doing it, because CUA could see the page: "The click caused the
website chips/badges below the 'Searched 20 websites' line to collapse/hide"
(03:06:40), then "the second click just re-expanded the website chips dropdown
again" (03:07:05). That is #913's toggle storm exactly, resurrected by a verifier
blind to a new shape — and the run's whole P1 phase logged ZERO
`panel tracking (P1)` lines across 13.7 minutes, which is the empty raw-activity
popup the owner reported.

── Why the repair is P1-SCOPED and not a looser shared rule ──────────────────

⛔ `inline_expanded` also guards P2, whose side panel parses correctly (same run,
03:12:42, shape=side, 5 URLs) and whose iframe-embedded DR card is the entire
reason for the 40-char floor. Loosening the shared predicate would let P2 latch
"already open" on any small in-turn node and never click its strip — the
2026-08-06 regression that cost a phase its narration. So the chip row is
reported as its OWN fact and only `_chatgpt_p1_activity_open` treats it as open.

── The owner's constraint, and what it rules out ─────────────────────────────

⛔ NO HARDCODED LABELS. The shimmer text is topic-specific and rewrote itself
every few seconds across the measured phase — "Mapped security coverage",
"Compared security layers", "Searching the web", "Searched 20 websites" — and not
one of those ended in the "..." that a 2026-05-03 comment called an invariant.
So both the line and the drawer are recognised STRUCTURALLY: an animated gradient
masked to its glyphs for the line, and a row of ≥2 hostname-only leaves for the
drawer.

── What is measured here vs. what is pinned ─────────────────────────────────

The JS half is exercised in a REAL browser (system Chrome, headless, ~0.8s for all
fourteen) against fixture DOMs rebuilt from the panel-miss snapshots of that run.
Those tests SKIP where Chrome is absent, so every structural property they rely on
also has a source pin that runs everywhere — a skipped test is not a test. Both
layers were confirmed live: mutating `out.chips >= 2` to `>= 999` turns two of the
browser tests red as well as the pin.
"""
import json

import pytest

import research

from conftest import code_only, code_only_deep, js_code_only


# ══════════════════════════════════════════════════════════════════════════
#  1. The P1-scoped open predicate — the gate that was blind
# ══════════════════════════════════════════════════════════════════════════

def test_a_chip_row_counts_as_open_for_P1():
    """⭐⭐ THE FIX. This is the state the callers read as "collapsed" eight times."""
    st = {"side_panel": False, "inline_expanded": False,
          "inline_chip_row": True, "inline_chips": 8}
    assert research._chatgpt_p1_activity_open(st) is True


def test_a_chip_row_does_NOT_count_for_P2():
    """⛔ P2 reads `side_panel or inline_expanded` and must keep doing so. If the
    chip row leaked into P2's gate it would latch "already open" and never click
    the DR strip — 2026-08-06, one whole phase of narration lost."""
    st = {"side_panel": False, "inline_expanded": False,
          "inline_chip_row": True, "inline_chips": 8}
    assert not (st.get("side_panel") or st.get("inline_expanded"))
    src = code_only_deep(research.poll_all_agents_round_robin)
    # The P2 gates name the two original keys and never the chip key.
    assert "inline_chip_row" not in src, (
        "P2's round-robin must not read the chip row — see the 2026-08-06 note")


def test_the_old_two_shapes_still_open_it():
    for key in ("side_panel", "inline_expanded"):
        assert research._chatgpt_p1_activity_open({key: True}) is True


def test_nothing_open_is_not_open():
    assert research._chatgpt_p1_activity_open({}) is False
    assert research._chatgpt_p1_activity_open(None) is False
    assert research._chatgpt_p1_activity_open(
        {"side_panel": False, "inline_expanded": False,
         "inline_chip_row": False, "inline_chips": 1}) is False


def test_one_chip_is_not_a_row():
    """⛔ The ≥2 rule lives in the JS, so the state dict is the contract: a lone
    hostname (ordinary prose, a single citation) must arrive with chip_row False
    and must not open the gate on the count alone."""
    assert research._chatgpt_p1_activity_open(
        {"inline_chip_row": False, "inline_chips": 1}) is False


# ══════════════════════════════════════════════════════════════════════════
#  2. The shape label — for the log, and ORDERED
# ══════════════════════════════════════════════════════════════════════════

def test_the_shape_names_what_the_walker_will_actually_read():
    """A side panel present alongside a chip row is a SIDE run: that is the shape
    `scrape_chatgpt_activity_panel_tracking` reads from, so calling it "chips"
    would send the next reader to the wrong half of the walker."""
    assert research._chatgpt_open_shape(
        {"side_panel": True, "inline_chip_row": True}) == "side"
    assert research._chatgpt_open_shape(
        {"inline_expanded": True, "inline_chip_row": True}) == "inline"
    assert research._chatgpt_open_shape({"inline_chip_row": True}) == "chips"
    assert research._chatgpt_open_shape({}) == "none"


# ══════════════════════════════════════════════════════════════════════════
#  3. Chips → sources. A chip is not a URL.
# ══════════════════════════════════════════════════════════════════════════

def test_a_hostname_chip_becomes_a_followable_url():
    res = {"source_urls": [], "source_items": []}
    research._merge_host_chips(res, ["www.nvidia.com", "github.com"])
    assert res["source_urls"] == ["https://www.nvidia.com/", "https://github.com/"]
    assert res["source_items"] == [
        {"url": "https://www.nvidia.com/", "title": "www.nvidia.com"},
        {"url": "https://github.com/", "title": "github.com"}]
    assert res["chip_hosts_added"] == 2


def test_a_host_already_carrying_a_real_page_gets_no_bare_twin():
    """⛔ The count is compared against ChatGPT's own "Searched 20 websites", so
    one source listed twice is a wrong answer, not untidiness."""
    res = {"source_urls": ["https://github.com/NVIDIA/nemo"], "source_items": []}
    research._merge_host_chips(res, ["github.com"])
    assert res["source_urls"] == ["https://github.com/NVIDIA/nemo"]
    assert "chip_hosts_added" not in res


def test_the_same_chip_twice_is_one_source():
    res = {"source_urls": [], "source_items": []}
    research._merge_host_chips(res, ["github.com", "GitHub.com", "github.com."])
    assert res["source_urls"] == ["https://github.com/"]


def test_a_chip_that_is_not_a_host_is_refused():
    """The row ends in an "N more" affordance and could hold anything; a value
    with a slash is a path, not a host, and would build a nonsense URL."""
    res = {"source_urls": [], "source_items": []}
    research._merge_host_chips(res, ["", None, "13 more", "github.com/NVIDIA"])
    assert res["source_urls"] == []


def test_no_hosts_leaves_the_result_untouched():
    res = {"source_urls": ["https://a.example/x"], "source_items": [{"url": "https://a.example/x"}]}
    before = json.dumps(res, sort_keys=True)
    research._merge_host_chips(res, [])
    assert json.dumps(res, sort_keys=True) == before


# ══════════════════════════════════════════════════════════════════════════
#  4. …and the other half: arrival order
# ══════════════════════════════════════════════════════════════════════════

def test_a_placeholder_is_dropped_once_a_real_page_on_its_host_arrives():
    """⛔⛔ THE HALF `_merge_host_chips` CANNOT DO. The chip is seen at minute two
    and the page at minute nine, and the caller ACCUMULATES — so deduping only at
    insert time still ends the run with both."""
    urls = ["https://github.com/", "https://docs.nvidia.com/",
            "https://github.com/NVIDIA/nemo"]
    items = [{"url": u, "title": ""} for u in urls]
    urls2, items2 = research._drop_covered_host_placeholders(
        urls, items, ["github.com", "docs.nvidia.com"])
    assert urls2 == ["https://docs.nvidia.com/", "https://github.com/NVIDIA/nemo"]
    assert [i["url"] for i in items2] == urls2


def test_a_GENUINE_homepage_citation_is_never_dropped():
    """⛔⛔⛔ THE DEFECT A MUTATION SURVIVOR EXPOSED IN MY OWN FIX. A synthesised
    placeholder and a real citation of a project's home page are the SAME STRING —
    `https://nvidia.com/` — so a shape-only prune deleted a source ChatGPT actually
    cited the moment any deeper page on that host arrived. Only a host this run took
    from a CHIP may lose its bare entry."""
    urls = ["https://nvidia.com/", "https://nvidia.com/blog/x"]
    items = [{"url": u, "title": ""} for u in urls]
    urls2, items2 = research._drop_covered_host_placeholders(urls, items, ["github.com"])
    assert urls2 == urls, "a homepage nobody scraped from a chip is a real source"
    assert len(items2) == 2
    # …and with no provenance at all, nothing is prunable.
    assert research._drop_covered_host_placeholders(urls, items, [])[0] == urls
    assert research._drop_covered_host_placeholders(urls, items, None)[0] == urls


def test_the_provenance_set_is_matched_case_and_dot_insensitively():
    """The hosts arrive from three places — the JS chip scan, an accumulated
    `progress` list, and a re-read — so one of them arriving as `GitHub.com.` must
    not quietly make the entry unprunable."""
    urls = ["https://github.com/", "https://github.com/a"]
    urls2, _ = research._drop_covered_host_placeholders(urls, [], ["GitHub.com."])
    assert urls2 == ["https://github.com/a"]


def test_a_host_with_only_a_placeholder_keeps_it():
    """⛔ Dropping every bare domain would delete the chip row outright on a P1
    run, where a bare domain is the only address that exists — which is the data
    the owner asked to be shown."""
    urls = ["https://github.com/", "https://docs.nvidia.com/"]
    urls2, _ = research._drop_covered_host_placeholders(
        urls, [], ["github.com", "docs.nvidia.com"])
    assert urls2 == urls


def test_arrival_order_survives():
    """`progress` and the trailing slices read the NEWEST row, so reordering the
    list would silently move which source is treated as latest."""
    urls = ["https://a.example/1", "https://b.example/", "https://c.example/2",
            "https://b.example/3"]
    urls2, _ = research._drop_covered_host_placeholders(urls, [], ["b.example"])
    assert urls2 == ["https://a.example/1", "https://c.example/2", "https://b.example/3"]


def test_a_query_only_url_is_a_real_page_not_a_placeholder():
    """`https://h/?q=1` names a page. Treating it as bare would let a placeholder
    survive next to it."""
    urls = ["https://x.example/", "https://x.example/?q=1"]
    urls2, _ = research._drop_covered_host_placeholders(urls, [], ["x.example"])
    assert urls2 == ["https://x.example/?q=1"]


def test_junk_entries_do_not_take_the_list_with_them():
    urls = ["not a url", "https://x.example/", "https://x.example/p"]
    urls2, _ = research._drop_covered_host_placeholders(urls, [], ["x.example"])
    assert urls2 == ["not a url", "https://x.example/p"]


def test_merge_records_which_hosts_it_invented_an_address_for():
    """⛔ The provenance has to be recorded where it SURVIVES: the caller's
    source_items merge rebuilds every entry as exactly {url, title}, so a flag on
    an item would be gone after one poll. Hosts on the result, not flags on items."""
    res = {"source_urls": ["https://github.com/NVIDIA/nemo"], "source_items": []}
    research._merge_host_chips(res, ["github.com", "docs.nvidia.com"])
    assert res["chip_hosts"] == ["docs.nvidia.com"], (
        "github.com was already covered, so no address was invented for it")


def test_merge_accumulates_provenance_across_polls():
    res = {"source_urls": [], "source_items": [], "chip_hosts": ["alpha.example"]}
    research._merge_host_chips(res, ["beta.example"])
    assert res["chip_hosts"] == ["alpha.example", "beta.example"]


def test_the_host_pattern_is_conservative_and_that_is_RECORDED():
    r"""⚠ NOT A BUG THIS WAVE INTRODUCED, but a limit worth writing down rather than
    tripping over: `^[a-z0-9][a-z0-9.-]{2,60}\.[a-z]{2,10}$` needs at least three
    characters before the final dot, so a genuinely short host — `t.co`, the link
    shortener that appears in real citations — is REFUSED. The failure direction is
    the safe one (a chip is missed, never invented), and this is the shape the JS
    walker has used since it shipped; matching it in Python is the point, so a
    future loosening has to loosen BOTH or the two halves disagree."""
    res = {"source_urls": [], "source_items": []}
    research._merge_host_chips(res, ["t.co", "abc.co"])
    assert res["source_urls"] == ["https://abc.co/"]


# ══════════════════════════════════════════════════════════════════════════
#  5. The CONSUMERS. Extracting a helper does not wire it in.
# ══════════════════════════════════════════════════════════════════════════

def test_all_three_P1_gates_use_the_P1_predicate():
    """⛔⛔ THE ACTUAL BUG WAS AT THE CALL SITES, not in any helper: the per-cycle
    re-check that un-latched an open drawer, the anti-toggle pre-check that
    decided to press, and the post-press verify. A helper nothing calls fixes
    nothing, so all three are pinned as CODE."""
    src = code_only_deep(research.poll_until_done)
    assert src.count("_chatgpt_p1_activity_open(") == 3, (
        "expected the re-check, the pre-check and the post-verify")
    for stale in ('_st_now.get("side_panel") or _st_now.get("inline_expanded")',
                  '_st_pre.get("side_panel") or _st_pre.get("inline_expanded")',
                  '_st_post.get("side_panel")'):
        assert stale not in src, f"a P1 gate still reads the old pair: {stale}"


def test_the_walk_prunes_placeholders_after_merging_not_before():
    """⛔ Order is the whole point. Pruning the fresh scrape instead of the
    accumulated list cannot see the placeholder that arrived seven polls ago."""
    src = code_only_deep(research.poll_until_done)
    prune = src.index("_drop_covered_host_placeholders(")
    items = src.index('progress["source_items"] = list(_by_url.values())')
    assert items < prune, "the prune must run after the source_items merge"
    tail = src[prune:prune + 600]
    assert 'progress["sources"] = len(' in tail, (
        "the count must be recomputed from the pruned list")


def test_the_walk_ACCUMULATES_the_chip_host_set():
    """⛔ A mutation survivor found this missing. The prune's whole reason is that a
    chip arrives minutes before a page on the same host, so the provenance set has
    to survive across polls exactly like the URL list does. Replacing it with this
    poll's hosts makes a host chipped at minute two unprunable at minute nine, and
    the run ends with one source listed twice — which is the defect the prune
    exists to stop, restored via its own input."""
    src = code_only_deep(research.poll_until_done)
    i = src.index('progress["chip_hosts"] = sorted(')
    stmt = src[i:src.index('progress["source_urls"], progress["source_items"]', i)]
    assert 'set(progress.get("chip_hosts") or [])' in stmt, (
        "the union must include what earlier polls already recorded")
    assert 'set(_pd.get("chip_hosts") or [])' in stmt, (
        "…and what this poll just found")
    # …and the pruned call is handed that accumulated set, not a fresh one.
    call = src[src.index("_drop_covered_host_placeholders(", i):]
    assert 'progress["chip_hosts"]))' in call[:400]


def test_the_scraper_passes_the_chips_through():
    src = code_only_deep(research.scrape_chatgpt_activity_panel_tracking)
    assert "_merge_host_chips(res" in src
    assert 'il.get("source_hosts")' in src
    # …and a chips-only sample is not thrown away, which is the one sample that
    # proves a drawer open before any verb row has streamed.
    assert 'or int(il.get("chips", 0) or 0)' in src


class _ExtractPage:
    """A page for `scrape_progress_chatgpt`, keyed on WHICH js it is handed.

    ⭐ The inline walker is a module constant, so identity tells it apart from the
    two inline literals — the same trick `test_913_chatgpt_panel_shapes` uses. The
    frame list is empty, which is the P1 shape: no Deep Research iframe.
    """

    def __init__(self, host, inline):
        self._host = host
        self._inline = inline
        self.frames = []
        self.main_frame = None

    async def evaluate(self, js):
        if js is research._CHATGPT_INLINE_ACTIVITY_JS:
            return self._inline
        # The host-page scrape comes first; the host-PANEL scrape after it must
        # return nothing, or its own union would confuse what we are measuring.
        if "panel_found" in js:
            return None
        return dict(self._host)


def _extract(host, inline):
    import asyncio
    return asyncio.run(research.scrape_progress_chatgpt(_ExtractPage(host, inline)))


def test_the_EXTRACTED_result_carries_the_chip_row():
    """⭐⭐ THE WORST THING THE REVIEW OF THIS WAVE FOUND, and a mutation survivor
    proved the test was missing too. The live walk merges the chips into
    `progress`, so the FE activity popup fills with domains all through the phase —
    and `scrape_progress_chatgpt` builds the EXTRACTED result, which is what the
    report and the final source list come from. Without this the finished run
    showed none of them: two views of one run disagreeing, which is the class of
    bug this wave was opened for."""
    out = _extract(
        {"source_urls": [], "sources": 0},
        {"source_hosts": ["github.com", "docs.nvidia.com"], "source_urls": [],
         "chips": 2, "chip_row": True})
    assert out["source_urls"] == ["https://github.com/", "https://docs.nvidia.com/"]
    assert out["sources"] == 2


def test_the_EXTRACTED_result_prefers_a_real_page_over_the_chip_for_that_host():
    """⛔ GAP-FILL ONLY. A finished response has rendered its real citation links,
    and a page URL beats the domain it lives on. Keeping both would list one source
    twice under a count the owner compares with ChatGPT's own figure."""
    out = _extract(
        {"source_urls": ["https://github.com/NVIDIA/nemo"], "sources": 1},
        {"source_hosts": ["github.com", "docs.nvidia.com"], "source_urls": [],
         "chips": 2, "chip_row": True})
    assert out["source_urls"] == ["https://github.com/NVIDIA/nemo",
                                  "https://docs.nvidia.com/"]
    assert out["sources"] == 2
    assert "https://github.com/" not in out["source_urls"]


def test_the_EXTRACTED_result_is_untouched_when_there_is_no_chip_row():
    out = _extract(
        {"source_urls": ["https://a.example/x"], "sources": 1},
        {"source_hosts": [], "source_urls": [], "chips": 0, "chip_row": False})
    assert out["source_urls"] == ["https://a.example/x"]
    assert out["sources"] == 1


def test_the_state_helper_reports_the_chip_row_without_folding_it_in():
    src = code_only_deep(research._chatgpt_activity_state)
    assert 'out["inline_chip_row"] = bool(il.get("chip_row"))' in src
    assert 'out["inline_chips"] = int(il.get("chips", 0) or 0)' in src
    assert 'out["inline_expanded"] = bool(il.get("expanded"))' in src, (
        "inline_expanded must keep its own strict meaning for P2")


def test_the_miss_line_reports_the_chip_delta():
    """A toggle press that misses is ambiguous in the one way that matters — did
    we fail to open, or did we just close it? On 19 August it was the second,
    eight times, and no line said so."""
    src = code_only_deep(research.poll_until_done)
    assert 'chips {_cb}->{_ca}' in src
    assert "THE PRESS CLOSED AN OPEN DRAWER" in src


def test_the_inline_diagnostic_is_signature_gated_not_per_poll():
    """⛔⛔ The same instinct un-sparsely applied put 412 byte-identical DEBUG
    lines into yesterday's bundle. A walk that keeps failing the same way says so
    once; a walk that starts failing a NEW way says so immediately."""
    src = code_only_deep(research.scrape_chatgpt_activity_panel_tracking)
    assert "_p1_inline_dbg_sig" in src
    assert "if _sig != _p1_inline_dbg_sig:" in src


# ══════════════════════════════════════════════════════════════════════════
#  6. Structural pins on the JS — these run even where Chrome does not
# ══════════════════════════════════════════════════════════════════════════

def _inline_js():
    return js_code_only(research._CHATGPT_INLINE_ACTIVITY_JS)


def test_the_chip_test_is_structural_and_names_no_label():
    js = _inline_js()
    assert "chipTop.set(host" in js
    assert "out.chip_row = out.chips >= 2;" in js
    # No topic wording, no class hook, no testid: the row is recognised by shape.
    # No class hook, no testid, no topic wording. (`websites` DOES appear — in
    # the count regex, which is page vocabulary rather than a label, and the
    # chip test does not consult it.)
    for banned in ('"flex"', "text-token-text-tertiary", "Searched security",
                   "Searching the web", "Mapped security", "nvidia"):
        assert banned not in js, f"a hardcoded label leaked into the chip test: {banned}"


def test_the_hostname_test_is_anchored_at_both_ends():
    """An unanchored host pattern would match any sentence containing a domain
    and turn the report prose into a chip row."""
    js = _inline_js()
    assert "const HOSTCHIP = /^[a-z0-9][a-z0-9.-]{2,60}\\.[a-z]{2,10}$/i;" in js


def test_prose_chips_are_excluded_and_counted_separately():
    js = _inline_js()
    assert "if (isChip && !inProse) {" in js
    assert "proseChips.add(" in js


def test_the_expensive_shimmer_check_is_gated_on_being_able_to_matter():
    """⛔ `shimmerLine` walks the subtree calling getComputedStyle on every
    descendant. In an `||` chain it ran for nearly every candidate — hundreds of
    style resolutions per poll — when the answer can only change the outcome for a
    row ABOVE the best so far. And the same restructure is what lets the diagnostic
    name the term that actually fired instead of guessing afterwards."""
    js = _inline_js()
    assert "else if (t.length <= 240 && r.top < statusTop && shimmerLine(el)) from = 'shimmer';" in js
    assert "out.dbg.statusFrom = from;" in js
    # Each term sets its own label, in the order they are actually tried.
    for term, label in (("STATUS_LINE.test(t) && t.length <= 60", "word"),
                        ("ELLIPSIS.test(t) && t.length >= 8 && t.length <= 240", "ellipsis"),
                        ("COUNT.test(t) && t.length <= 160", "count")):
        assert f"({term}) from = '{label}';" in js


def test_the_chip_COUNT_is_not_capped_even_though_the_list_is():
    js = _inline_js()
    assert "out.chips = chipTop.size;" in js
    assert "out.source_hosts = [...chipTop.keys()].slice(0, 60);" in js


def test_the_shimmer_anchor_requires_BOTH_animation_and_clipped_text():
    """⛔ `animKid` alone matched the "Pro" badge in every panel-miss snapshot of
    the 19 August run (anim:false, animKid:true, clip:FALSE) while the real status
    line was clip:true in all four. One term alone picks the badge."""
    js = _inline_js()
    assert "if (anim && clip) return true;" in js
    assert "webkitBackgroundClip === 'text'" in js
    assert "animationPlayState !== 'paused'" in js


def test_the_count_regex_knows_the_words_the_page_actually_uses():
    """The status line came back empty all phase because this alternation lacked
    `websites`, while the aggregate-count regex in the same function has had it
    since it shipped."""
    js = _inline_js()
    assert "websites?|sites?|searches?|sources?|results?|citations?" in js


def test_progress_prefers_a_sentence_over_a_hostname():
    js = _inline_js()
    assert "out.progress = out.status_line || lastVerbStep || lastStep;" in js
    assert "if (VERB.test(t)) lastVerbStep = t.slice(0, 220);" in js


def test_the_geometric_pass_is_a_FALLBACK_and_stays_bounded():
    """⛔ It must not run when the article scope worked — broadening the scan on a
    working page is how the composer and the footer get into `steps`. And it is
    bounded below the last user message, the same bound the panel-miss snapshot
    uses."""
    js = _inline_js()
    assert "if (!out.status_line && !chipTop.size && !out.steps.length && lub > 0) {" in js
    assert "if (inGeo && lub > 0 && (r.top < lub - 8 || r.top > lub + 900)) continue;" in js


def test_the_strict_inline_expanded_gates_are_still_there():
    """⛔ Not loosened, not deleted: P2's iframe DR card is why the 40-char floor
    exists, and this predicate is shared."""
    js = _inline_js()
    assert "if (r.height < 60 || r.width < 120) continue;" in js
    assert "if (((el.innerText || '').trim()).length < 40) continue;" in js


def test_the_shim_resolves_the_composed_picker_constant():
    """⛔⛔ THE SHIM HAD TO LEARN THE SAME LESSON IT TEACHES. Extracting the shimmer
    helpers turned the picker's `JS` from a literal into a concatenation, and
    `js_constant`'s AST walk matched only `ast.Constant` — so eleven anchor tests
    failed with "JS not found", a message that reads like a renamed constant.

    Pinned here because the dangerous version of that bug is the SILENT one: a fold
    that returned "" instead of raising would hand node an empty program and every
    one of those eleven tests would pass having executed nothing."""
    from _domshim import js_constant
    js = js_constant(research._open_chatgpt_activity_panel, "JS")
    # Both halves of the concatenation, and the spliced fragment between them.
    assert "const shimmers = (n) =>" in js
    assert "const ELLIPSIS" in js
    assert len(js) > 5000, "the picker's JS is thousands of characters; this is a stub"


def test_the_shim_refuses_a_constant_it_cannot_resolve():
    """…and it must RAISE rather than return a stub, or the fold's own failure mode
    is a suite that measures nothing."""
    from _domshim import js_constant

    def _bad():
        JS = 1 + 2          # noqa: F841 — deliberately not string-shaped
        return JS

    with pytest.raises(AssertionError, match="cannot resolve to a string"):
        js_constant(_bad, "JS")


def test_the_ellipsis_anchor_survives_for_P2():
    """⛔ The 2026-08-19 measurement killed the claim that the ellipsis is
    universal, not the anchor: the same run's P2 strip opened off "Researching..."
    Deleting it would take a working leg with it."""
    opener = js_code_only(code_only(research._open_chatgpt_activity_panel))
    # Four backslashes: `opener` is Python SOURCE, where the JS regex is written
    # with doubled escapes inside a non-raw string literal.
    assert "const ELLIPSIS = /(?:\\\\.{3}|\\\\u2026)\\\\s*$/;" in opener
    assert "ELLIPSIS.test(t)" in _inline_js()


# ══════════════════════════════════════════════════════════════════════════
#  7. The vision hints and the CUA brief must describe THIS UI
# ══════════════════════════════════════════════════════════════════════════

def test_the_p1_success_signals_no_longer_demand_a_panel_that_cannot_appear():
    """⛔⛔ `success_signals` is what the shadow observer scores a CUA attempt
    against, so a signal that cannot occur marks every correct attempt a failure.
    CUA opened the drawer at 02:59:01 and described it accurately against an
    instruction demanding "a right-side panel with a numbered step list"."""
    hints = research._HOTSPOT_VISION_HINTS["7c-p1"]
    joined = " ".join(hints["success_signals"]).lower()
    assert "chip" in joined
    assert "side panel" not in hints["expected_outcome"].lower()
    assert "right" not in joined.replace("directly", ""), (
        "a right-side panel is not what P1 does any more")
    # The hint must say the ellipsis is ABSENT here, not merely omit it — the old
    # text told the model to expect one.
    assert "do not expect a trailing '...'" in hints["context_hint"]
    assert "WORDING IS\nTOPIC-SPECIFIC" in hints["context_hint"].replace(" ", " ") or \
           "TOPIC-SPECIFIC" in hints["context_hint"]


def test_the_p2_hint_is_untouched():
    """⛔ P2's side panel opened normally on the same run off a label that DID end
    in dots. Scope discipline: this wave changes P1 only."""
    hints = research._HOTSPOT_VISION_HINTS["7c"]
    assert "side panel" in hints["expected_outcome"].lower() or "right" in hints["expected_outcome"].lower()
    assert "'...'" in hints["context_hint"]


def test_the_shared_CUA_prompt_teaches_both_shapes_and_the_look_before_click_rule():
    import prompts
    p = prompts.PROMPT_OPEN_CHATGPT_SOURCE_PANEL
    assert "THE SHIMMER IS THE ANCHOR" in p
    assert "is ALREADY showing under the activity line" in p
    # The prompt no longer asserts the ellipsis as universal…
    assert "ALWAYS ends with three dots" not in p
    # …while still telling the model it is a strong P2 hint.
    assert "It is NOT required" in p
    # One restore click is sanctioned, and the old blanket ban is gone, or the
    # instruction to restore would contradict the hard constraints.
    assert "DO NOT click twice. ONE click only." not in p
    assert "one restoring click is" in p and "allowed and required" in p
    # ⛔ BOTH HALVES. A survivor proved this: dropping the ACTION-section clause
    # that tells the model HOW to restore left the hard-constraints exception in
    # place, so the prompt permitted a second click and never said what it was for
    # — and the drawer stays closed. The permission and the instruction are one
    # rule in two places, and a test that pins one is a test that pins neither.
    assert "click the SAME line once more to restore it" in p
    # …and the chip clause must stay P1-SCOPED, or a Deep Research turn that ever
    # shows chips would report already_open and P2 would never open the side panel
    # its walker reads.
    assert "IN PRO / EXTENDED THINKING (P1) ONLY" in p
    assert "IN DEEP RESEARCH (P2), chips alone are NOT enough" in p


def test_the_p1_cua_brief_expects_chips_not_a_panel():
    # ⛔ Sliced to the NEXT construct, never a byte window: a fixed window slid
    # past the line under test the moment the brief grew, and the assertion then
    # failed for a reason that had nothing to do with the brief.
    src = code_only(research.poll_until_done)
    i = src.index("async def _cgpt_p1_cua")
    brief = src[i:src.index("model=CUA_MODEL", i)]
    assert "website chips" in brief
    assert "Activity · <seconds>" not in brief
    assert "it is already open — do not click at all" in brief


# ══════════════════════════════════════════════════════════════════════════
#  8. The JS, in a real browser, against the measured DOM
# ══════════════════════════════════════════════════════════════════════════
#
# Rebuilt from the panel-miss snapshots of the 19 August run: a status line whose
# text is masked to an animated gradient, and beneath it hostname-only leaves
# inside `class="flex"` containers, plus the "13 more" affordance that is not a
# hostname. Every case below was RUN and its expectation is what Chrome returned.

_CSS = """
<style>
 body{margin:0;font-family:sans-serif} main{width:1280px}
 @keyframes shine{0%{background-position:0}100%{background-position:200px}}
 .shimmer{animation:shine 2s linear infinite;
          background:linear-gradient(90deg,#111,#999,#111);
          -webkit-background-clip:text;background-clip:text;color:transparent}
 @keyframes fade{0%{opacity:.4}100%{opacity:1}}
 .badge{animation:fade 1s linear infinite}
 .flex{display:inline-flex;gap:4px;margin:2px;padding:4px 8px;background:#eee}
 .user{padding:24px;background:#111;color:#fff}
</style>"""

_HOSTS = ["www.nvidia.com", "github.com", "docs.nvidia.com", "nemoclawai.io",
          "cobusgreyling.medium.com", "build.nvidia.com", "www.penligent.ai"]

_USER = ('<article data-testid="conversation-turn-1">'
         '<div data-message-author-role="user"><div class="user">'
         'Please create a detailed research report brief.</div></div></article>')


def _chip_row():
    cells = "".join(f'<div class="flex"><img width=14 height=14>'
                    f'<span>{h}</span></div>' for h in _HOSTS)
    return "<div>" + cells + ('<div class="flex"><img width=14 height=14>'
                              '<span>13 more</span></div>') + "</div>"


def _turn(status, chips=False, prose="", shimmer=True):
    cls = "shimmer" if shimmer else "badge"
    html = f'<div class="text-token-text-tertiary"><span class="{cls}">{status}</span></div>'
    if chips:
        html += _chip_row()
    if prose:
        html += f'<div class="markdown">{prose}</div>'
    return html


def _page(turn_html, in_article=True):
    body = _USER + (f'<article data-testid="conversation-turn-2">{turn_html}</article>'
                    if in_article else turn_html)
    return (_CSS + f"<main>{body}</main>"
            "<div class='mt-auto'>ChatGPT can make mistakes. Check important info.</div>")


@pytest.fixture(scope="module")
def chrome():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:                                    # pragma: no cover
        pytest.skip(f"playwright unavailable: {e}")
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(channel="chrome", headless=True)
    except Exception as e:                                    # pragma: no cover
        pw.stop()
        pytest.skip(f"system Chrome unavailable: {e}")
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    yield page
    browser.close()
    pw.stop()


def _walk(chrome, html):
    chrome.set_content(html)
    return chrome.evaluate(research._CHATGPT_INLINE_ACTIVITY_JS)


def test_live_the_expanded_chip_row_reads_as_a_row(chrome):
    r = _walk(chrome, _page(_turn("Searching the web", chips=True)))
    assert r["chip_row"] is True
    assert r["chips"] == len(_HOSTS)
    assert r["source_hosts"] == _HOSTS
    assert "13 more" not in r["source_hosts"]


def test_live_a_collapsed_drawer_reads_as_closed(chrome):
    """The thinking phase: a status line and nothing under it."""
    r = _walk(chrome, _page(_turn("Mapped security coverage")))
    assert r["chip_row"] is False and r["chips"] == 0
    assert r["status_line"] == "Mapped security coverage"
    assert r["dbg"]["statusFrom"] == "shimmer"


def test_live_chips_kept_in_the_DOM_but_hidden_read_as_closed(chrome):
    """⛔⛔ THE LATCH-FOREVER TRAP. A collapsed drawer may keep its chips mounted;
    counting those would make the pre-check say "open" for the rest of the phase
    and the drawer would never be opened again."""
    html = _page('<div><span class="shimmer">Searching the web</span></div>'
                 '<div style="display:none">'
                 '<div class="flex"><span>github.com</span></div>'
                 '<div class="flex"><span>docs.nvidia.com</span></div></div>')
    r = _walk(chrome, html)
    assert r["chips"] == 0 and r["chip_row"] is False


def test_live_report_citations_are_not_a_chip_row(chrome):
    """Once the report streams, the prose carries hostname-only citation chips.
    Counting them would report "open" forever, and after the response completes
    that is a permanent false latch."""
    prose = ("<p>Body text about the topic.</p>"
             '<a href="https://a">www.nvidia.com</a>'
             '<a href="https://b">github.com</a>'
             '<a href="https://c">docs.nvidia.com</a>')
    r = _walk(chrome, _page(_turn("Mapped security coverage", prose=prose)))
    assert r["chip_row"] is False and r["chips"] == 0
    assert r["dbg"]["chipsProse"] == 3


def test_live_real_chips_win_over_a_prose_citation_in_the_same_turn(chrome):
    html = _page('<div><span class="shimmer">Searching the web</span></div>'
                 '<div><div class="flex"><span>github.com</span></div>'
                 '<div class="flex"><span>docs.nvidia.com</span></div></div>'
                 '<div class="markdown"><a href="#">evil.example.org</a></div>')
    r = _walk(chrome, html)
    assert r["source_hosts"] == ["github.com", "docs.nvidia.com"]
    assert r["dbg"]["chipsProse"] == 1


def test_live_one_chip_is_not_a_row(chrome):
    html = _page('<div><span class="shimmer">Searching the web</span></div>'
                 '<div><div class="flex"><span>github.com</span></div></div>')
    r = _walk(chrome, html)
    assert r["chips"] == 1 and r["chip_row"] is False


def test_live_the_TOPMOST_status_candidate_wins(chrome):
    """⛔ A mutation survivor found this: dropping `r.top < statusTop` from the
    assignment let the LAST matching row in document order win, because only the
    shimmer term carries that guard on its own. A completed count line below the
    live shimmer would then overwrite it, and the narration would report the step
    that just finished rather than the one running."""
    html = _page('<div><span class="shimmer">Searching the web</span></div>'
                 + _chip_row()
                 + '<div>Searched 20 websites</div>')
    r = _walk(chrome, html)
    assert r["status_line"] == "Searching the web"
    assert r["dbg"]["statusFrom"] == "shimmer"


def test_live_the_animated_badge_does_not_become_the_status_line(chrome):
    """The "Pro" badge is animated and NOT clipped to its text; every snapshot of
    the run recorded it as animKid:true, clip:false."""
    r = _walk(chrome, _page(_turn("Pro", shimmer=False)))
    assert r["status_line"] == ""
    assert r["dbg"]["statusFrom"] == ""


def test_live_a_count_line_is_found_without_a_shimmer(chrome):
    """"Searched 20 websites" is what the line becomes once searching ends — and
    it is the wording the old alternation could not see."""
    r = _walk(chrome, _page(_turn("Searched 20 websites", chips=True, shimmer=False)))
    assert r["status_line"] == "Searched 20 websites"
    assert r["dbg"]["statusFrom"] == "count"


def test_live_progress_is_the_status_line_not_a_hostname(chrome):
    """⛔ The narration line the owner saw was a bare domain: `progress` read the
    LAST step, and once the chip row rendered the last step was a hostname."""
    r = _walk(chrome, _page(_turn("Searching the web", chips=True)))
    assert r["progress"] == "Searching the web"
    assert r["progress"] not in r["source_hosts"]


def test_live_with_no_status_line_progress_is_the_verb_row_not_a_chip(chrome):
    """⛔ THE CASE THAT DISCRIMINATES THE ORDERING. When a status line IS found the
    old `status_line || lastStep` and the new `status_line || lastVerbStep ||
    lastStep` agree, so only a turn with a non-shimmering, count-free line can
    tell them apart — and that is a real state: the label stops animating between
    steps while the chip row stays."""
    r = _walk(chrome, _page(_turn("Searching the web", chips=True, shimmer=False)))
    assert r["status_line"] == ""
    assert r["progress"] == "Searching the web"
    assert r["progress"] not in r["source_hosts"]


def test_live_an_EARLIER_turns_chip_row_is_not_this_turns_drawer(chrome):
    """⛔⛔ THE FOLLOW-UP TRAP. Phase1-followup asks a second question in the SAME
    thread, so the previous answer's chip row is still on the page. Counting it
    would report "already open" before the new turn has a drawer at all, and the
    opener would then never run for the rest of the phase — the 2026-08-06 failure
    mode, arrived at from the other direction. The geometric pass is bounded below
    the LAST user message for exactly this reason."""
    old_turn = ('<article data-testid="conversation-turn-0">'
                '<div><span class="shimmer">Searched 9 websites</span></div>'
                + _chip_row() + '</article>')
    html = (_CSS + "<main>" + old_turn + _USER
            + '<article data-testid="conversation-turn-2">'
            '<div><span class="shimmer">Thinking</span></div></article></main>')
    r = _walk(chrome, html)
    assert r["chips"] == 0 and r["chip_row"] is False
    assert r["status_line"] == "Thinking"


def test_live_the_walk_survives_the_assistant_turn_not_existing_yet(chrome):
    """⛔⛔ MEASURED: the status line was recorded with `inTurn: false` at 02:56:08
    and 02:58:15, so for the first minutes `arts[last]` is the USER's turn and the
    article scope scans the wrong subtree. That is why the phase logged nothing."""
    r = _walk(chrome, _page(_turn("Searching the web", chips=True), in_article=False))
    assert r["chip_row"] is True
    assert r["status_line"] == "Searching the web"
    assert r["dbg"]["scope"].endswith("+geo")


def test_live_the_geometric_pass_does_not_run_when_the_article_scope_worked(chrome):
    r = _walk(chrome, _page(_turn("Searching the web", chips=True)))
    assert r["dbg"]["scope"] == "article"


def test_live_the_geometric_pass_ignores_the_footer_and_the_badge(chrome):
    """Broadening the scan must not drag the composer disclaimer into `steps`."""
    html = (_CSS + f"<main>{_USER}"
            "<div class='mt-auto'>ChatGPT can make mistakes. Check important info.</div>"
            "<div class='badge'>Pro</div></main>")
    r = _walk(chrome, html)
    assert r["steps"] == [] and r["chips"] == 0 and r["status_line"] == ""


def test_live_inline_expanded_stays_FALSE_for_a_chip_row(chrome):
    """⛔ The shared predicate must not move, or P2 latches on this shape."""
    r = _walk(chrome, _page(_turn("Searching the web", chips=True)))
    assert r["expanded"] is False


def test_live_a_STREAMED_RESPONSE_BODY_does_not_set_inline_expanded(chrome):
    """⛔⛔ THE SELECTOR IS THE SHARED PREDICATE'S ONLY REAL GUARD, and a mutation
    survivor is what proved this test was missing. Widening
    `[class*="thought" i], [class*="activity" i], [data-testid*="thought" i]` to `*`
    survived every other test here, because a one-line chip row is ~30px and the
    60px floor blocked it on its own. Once PROSE streams the turn is full of tall,
    wide, wordy elements and the height and text floors stop discriminating
    anything — so the class filter is what keeps `inline_expanded` from being true
    for every response in flight, and since P2 reads that key, a true here means P2
    never clicks its strip."""
    prose = "<p>" + ("A long paragraph of streamed report body text. " * 20) + "</p>"
    r = _walk(chrome, _page(_turn("Searching the web", chips=True, prose=prose)))
    assert r["expanded"] is False
    # …and the turn really did contain something the loosened selector would take,
    # or this test would pass against a fixture that cannot discriminate either.
    assert r["partial_text_len"] > 400


def test_live_a_genuine_thoughts_region_still_sets_inline_expanded(chrome):
    """…and it must still fire for the shape it was built for, or the fix has
    quietly deleted a leg instead of adding one."""
    html = _page('<div class="my-thoughts-panel" style="width:400px;height:200px">'
                 + ("Reasoning about the question in some detail. " * 3) + "</div>")
    r = _walk(chrome, html)
    assert r["expanded"] is True
