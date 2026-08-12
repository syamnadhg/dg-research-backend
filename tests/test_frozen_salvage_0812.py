"""Six minutes of salvage on a page we already knew had stopped.

The 2026-08-11 run, ChatGPT's leg, after the 90-minute ceiling fired:

    22:43:45  Auto-skip — ran past the 90-min limit. Salvaging partial output…
    22:43:47  CUA: opening the canvas   (12 vision iterations)
    22:45:32  waiting for the download event…            195s
    22:48:47  T3 copy with clipboard hijack…             200s
    22:49:42  All extraction methods failed (canvas may not have opened)

Five minutes and fifty-seven seconds. The DOM scrape had been byte-identical
for 84 minutes — 22 URLs, 3 steps, 1356 chars — and the vision agent, reading
pixels rather than markup, had described the same unfinished card thirty times.
There was no completed report on that page for a download button to export,
and every tier that went looking for one was spending time we had already
proven was wasted.

WHAT MAKES A LADDER WORTH RUNNING, AND WHY IT IS NOT "DID WE SCRAPE ANYTHING"

The obvious reading — skip the tiers when the scrape came back empty — is
backwards, and would break the case the tiers exist for. On 2026-04-28 a
perfectly healthy ChatGPT run with 1,289 sources read 0 chars and 0 sources to
every scraper we have (cross-origin iframe, 404 narrator) and its full report
came back through the CUA download tier and nothing else. A leg we have never
scraped one character from is a leg we are BLIND to, and those tiers are the
only channel left.

So the discriminator is the opposite: does the scrape WORK, and is it telling us
the page stopped? 08-11 read 1356 chars and 22 sources and then never moved
again. 04-28 read nothing, ever. One is a live window onto a frozen page; the
other is a blind spot over a working one.

WHAT THE FIX DOES

When the scrape works and has been flat for `SALVAGE_FROZEN_SEC`, salvage runs
with `browser=None, cua_client=None` — the extractors' own documented switch for
DOM-tier-only, and the exact call shape Phase 1 uses on every run. Cheap salvage
still happens, so a partial report is still mined; only the tiers that go
hunting for a finished document are dropped.

Applied at BOTH auto-skip salvage sites in the poller. The unacted-card firer
runs the same ladder off copy that literally reads "stayed frozen with no
response", and it carries a second cost the hard-cap site does not: its own
comment explains that a user Retry or Skip landing mid-salvage has to win, and a
six-minute ladder leaves that decision unserved for six minutes.

Two further auto-skip salvages are deliberately left alone, both because they
run only on a PARKED leg: the poller's parked hard cap and
`_resolve_parked_agent_decision`'s unanswered-timeout path. A parked leg
`continue`s above the growth checkpoint every tick, so its clock stops the
moment it parks — the decision would read "the page stopped" off a leg that is
only waiting for the user.
"""
import ast
import asyncio
import functools
import inspect
import re
import time

import pytest

import research
from conftest import code_only


@functools.lru_cache(maxsize=1)
def poller_src() -> str:
    return code_only(research.poll_all_agents_round_robin)


def leg(*, chars=0, sources=0, flat_for=0.0) -> dict:
    """A poll-loop entry with the three fields the decision reads."""
    return {"last_growth_len": chars, "last_growth_sources": sources,
            "last_growth_time": time.time() - flat_for}


# ------------------------------------------------------------ the decision


def test_a_readable_page_that_stopped_moving_is_frozen():
    """⭐ The 08-11 shape: 1356 chars and 22 sources, then 84 minutes of
    nothing."""
    assert research._frozen_to_a_working_scraper(
        leg(chars=1356, sources=22, flat_for=84 * 60), 1800) is True


def test_a_page_we_have_never_read_one_character_from_is_not(monkeypatch):
    """⛔ THE CASE THAT MUST NOT REGRESS. 2026-04-28: 1,289 real sources, 0/0 to
    every scraper, report recovered by the CUA download tier alone. Blind is not
    frozen, and the tiers are the only channel left."""
    assert research._frozen_to_a_working_scraper(
        leg(chars=0, sources=0, flat_for=10 * 3600), 1800) is False


@pytest.mark.parametrize("kw", [{"chars": 1}, {"sources": 1}])
def test_either_signal_alone_counts_as_readable(kw):
    """ChatGPT's activity panel yields sources with almost no text; Claude's
    artifact yields text with no URLs at all. Either proves we can see the
    page."""
    assert research._frozen_to_a_working_scraper(
        leg(flat_for=3600, **kw), 1800) is True


def test_a_page_that_moved_recently_is_not_frozen():
    """⛔ The salvage-a-partial-report path. A slow-but-producing agent that hit
    the ceiling mid-write still gets the whole ladder."""
    assert research._frozen_to_a_working_scraper(
        leg(chars=4000, sources=9, flat_for=60), 1800) is False


def test_the_boundary_is_inclusive():
    assert research._frozen_to_a_working_scraper(
        leg(chars=10, flat_for=1800), 1800) is True
    assert research._frozen_to_a_working_scraper(
        leg(chars=10, flat_for=1799), 1800) is False


def test_a_leg_with_no_bookkeeping_at_all_is_not_frozen():
    """An agent that never reached the growth checkpoint — a setup-failure leg,
    or a shape from an older run dir — must fall through to the full ladder
    rather than be treated as a frozen page."""
    assert research._frozen_to_a_working_scraper({}, 1800) is False


def test_a_readable_leg_with_no_growth_timestamp_is_not_frozen():
    """Missing means unknown, and unknown must never read as 'stopped ages
    ago'."""
    assert research._frozen_to_a_working_scraper(
        {"last_growth_len": 500}, 1800) is False


def test_the_decision_never_raises_on_a_junk_leg():
    """It runs on the auto-skip path, where an exception costs the run the whole
    salvage AND the finalize behind it."""
    assert research._frozen_to_a_working_scraper({"last_growth_len": None}, 1800) is False


# ------------------------------------------------------ the threshold it uses


def test_the_frozen_window_cannot_be_reached_before_the_arbiter_gives_up():
    """Two full no-growth windows. Each arbiter extension rewinds the clock by
    one, so this is only reachable after both are spent AND another window has
    passed — never on an agent the arbiter is still granting time to."""
    src = poller_src()
    frozen = re.search(r'SALVAGE_FROZEN_SEC = int\(os\.environ\.get\(\s*"DG_SALVAGE_FROZEN_SEC",\s*'
                       r'str\(STUCK_NO_GROWTH_SEC \* (\d+)\)\)\)', src)
    assert frozen, "SALVAGE_FROZEN_SEC is no longer derived from the no-growth window"
    assert int(frozen.group(1)) >= 2
    resets = int(re.search(r'_ARBITER_MAX_WORKING_RESETS = int\(os\.environ\.get\("DG_ARBITER_MAX_WORKING_RESETS", "(\d+)"\)\)',
                           src).group(1))
    assert resets == 2, (
        "the arbiter's extension count moved — the frozen window is a multiple "
        "of the no-growth window chosen against it and must move with it"
    )


# ------------------------------------------------- both salvage sites, checked


@functools.lru_cache(maxsize=1)
def poller_tree():
    return ast.parse(inspect.getsource(research.poll_all_agents_round_robin))


def extractor_calls():
    """Every `extract_fns[…](…)` call in the poller, as AST.

    There are seven. Five are NOT auto-skips and are deliberately untouched: a
    user Stop, a user Skip, a CUA error verdict, an agent disabled mid-pause,
    and the parked-decision resolver's own hard cap. The first four are the user
    or the agent saying the leg is over, where a finished report may well exist
    and the full ladder is what fetches it.

    The fifth is excluded for a sharper reason. A parked leg `continue`s long
    before the growth bookkeeping runs, so `last_growth_time` stops advancing
    the moment it parks — the decision below would read "frozen" off a leg that
    is merely waiting for the user, which is a different fact entirely.
    """
    return [n for n in ast.walk(poller_tree())
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Subscript)
            and getattr(n.func.value, "id", "") == "extract_fns"]


def frozen_aware_calls():
    """The two auto-skip salvage sites, found by the names their own scopes give
    them rather than by looking for the fix — which would make every assertion
    below circular."""
    out = []
    for node in ast.walk(poller_tree()):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        if isinstance(value, ast.BoolOp):          # `… or ""`
            value = value.values[0]
        if isinstance(value, ast.Await):
            value = value.value
        if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Subscript)
                and getattr(value.func.value, "id", "") == "extract_fns"):
            continue
        target = getattr(node.targets[0], "id", "")
        index = getattr(value.func.slice, "id", "")
        if target == "_as_partial" or (target == "_partial" and index == "_nm"):
            out.append(value)
    return out


def test_both_auto_skip_salvage_sites_were_found():
    """Fixing one of two identical sites is how a fix half-disappears and the
    next reader concludes it never worked."""
    assert len(frozen_aware_calls()) == 2
    assert len(extractor_calls()) == 7, (
        "an extraction call site was added or removed; if it is a new auto-skip "
        "it needs this decision, and if it is not it needs to stay untouched"
    )


def test_the_other_five_sites_still_get_the_whole_ladder():
    """⛔ Over-correction guard. A user Stop, a user Skip, a CUA error verdict,
    an agent disabled mid-pause and the parked resolver's hard cap all still run
    every tier — those are not frozen-page cases, and one of them is reached
    before the growth bookkeeping the decision reads even runs."""
    frozen = {c.lineno for c in frozen_aware_calls()}
    others = [c for c in extractor_calls() if c.lineno not in frozen]
    assert len(others) == 5
    for call in others:
        kw = {k.arg: k.value for k in call.keywords}
        for arg in ("browser", "cua_client"):
            assert isinstance(kw.get(arg), ast.Name) and kw[arg].id == arg, (
                f"a non-auto-skip extraction site had its {arg} made conditional"
            )


def test_the_parked_resolvers_own_salvage_is_excluded_for_the_same_reason():
    """There is a fourth auto-skip salvage, outside the poller entirely:
    `_resolve_parked_agent_decision`'s unanswered-timeout path for Claude's
    two-artifact card. It is excluded on the same grounds as the parked hard
    cap — it only ever runs on a parked leg, whose growth clock stopped when it
    parked — and it keeps the whole ladder."""
    src = code_only(research._resolve_parked_agent_decision)
    assert "_frozen_to_a_working_scraper" not in src
    at = src.index("extract_fns[name](")
    assert "browser=browser, cua_client=cua_client," in src[at:at + 200]
    assert "hv_blocked" in src[max(0, at - 500):at], (
        "the resolver's salvage lost its hands-off wall check"
    )


def test_the_parked_resolver_is_reached_before_the_growth_bookkeeping():
    """⛔ The reason the parked hard cap is excluded, asserted rather than
    asserted-in-a-comment. If the resolver ever moves below the checkpoint its
    growth fields become live and it becomes a candidate — and this is how
    anyone finds out."""
    src = poller_src()
    assert src.index('_parked = p.get("awaiting_decision")') < src.index(
        'p.setdefault("last_growth_time", p["start_time"])')


def test_both_sites_hand_the_extractor_none_only_when_the_page_is_frozen():
    """⭐ The fix, read off the syntax tree rather than the text. A comment
    cannot satisfy this, and neither can one of the two sites."""
    for call in frozen_aware_calls():
        kw = {k.arg: k.value for k in call.keywords}
        for arg in ("browser", "cua_client"):
            node = kw.get(arg)
            assert isinstance(node, ast.IfExp), (
                f"{arg} is passed unconditionally — this site still runs the "
                f"download and clipboard tiers on a page known to be frozen"
            )
            assert isinstance(node.body, ast.Constant) and node.body.value is None, (
                f"the frozen branch does not disable {arg}"
            )
            assert isinstance(node.orelse, ast.Name) and node.orelse.id == arg, (
                f"the healthy branch no longer passes the real {arg} — the full "
                f"ladder is gone, not just deferred"
            )


def test_both_sites_decide_with_the_shared_helper():
    """One rule, consulted twice. The duplicated-predicate shape is what lost
    every share link on 08-11 when the two copies drifted."""
    tree = ast.parse(inspect.getsource(research.poll_all_agents_round_robin))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_frozen_to_a_working_scraper"]
    assert len(calls) == 2
    for c in calls:
        assert any(getattr(a, "id", "") == "SALVAGE_FROZEN_SEC" for a in c.args), (
            "a salvage site is using its own threshold instead of the shared one"
        )


def test_the_frozen_branch_is_named_in_the_log_at_both_sites():
    """A salvage that silently does less is indistinguishable from a salvage
    that failed. Both sites say which they did, and why."""
    src = poller_src()
    assert src.count("salvaging from the DOM al") == 2
    for anchor in ("chars / ", "sources) and it has not "):
        assert src.count(anchor) >= 2


# ---------------------------------------------- what must survive at both sites


def test_the_verification_walled_skip_is_untouched():
    """⛔ The 2026-07-06 Cloudflare directive: never run the extraction ladder
    against a walled tab, at all, frozen or not."""
    src = poller_src()
    for anchor in ("_as_partial = await extract_fns[name](", "_partial = await extract_fns[_nm]("):
        at = src.index(anchor)
        assert "hv_blocked" in src[max(0, at - 1800):at], (
            "an auto-skip salvage site no longer sits behind the hands-off wall "
            "check — the Cloudflare directive forbids touching a walled tab"
        )
        assert "verification-walled tab" in src[max(0, at - 1800):at]


def test_both_sites_still_pass_what_they_salvaged_to_the_finalize():
    """Cheaper salvage is still salvage — the partial has to reach the result."""
    src = poller_src()
    assert src.count("partial=_as_partial") == 1
    assert src.count("partial=_partial") == 1


def test_the_tab_is_still_focused_before_the_dom_read():
    src = poller_src()
    for anchor in ("_as_partial = await extract_fns[name](", "_partial = await extract_fns[_nm]("):
        at = src.index(anchor)
        assert "switch_to_page" in src[at - 120:at]


def test_the_salvage_still_cannot_take_the_run_down():
    src = poller_src()
    for anchor in ("_as_partial = await extract_fns[name](", "_partial = await extract_fns[_nm]("):
        at = src.index(anchor)
        assert "Auto-skip salvage extract failed" in src[at:at + 500]


def test_the_unacted_firer_still_revalidates_after_the_salvage():
    """⛔ #955 adversarial finding #4: a user Retry or Skip that lands during the
    salvage must win. The fix shortens that window; it must not remove the
    check that closes it."""
    src = poller_src()
    at = src.index("extract_fns[_nm]")
    window = src[at:at + 1200]
    assert "if _did not in _pending_decisions or _nm not in pending:" in window
    assert "Auto-skip aborted" in window


def test_the_hard_cap_itself_is_unchanged():
    """⛔ The ceiling is weeks old, was not implicated, and is the only thing
    guaranteeing a run cannot hang on an absent operator."""
    src = poller_src()
    assert 'PER_AGENT_HARD_CAP_SEC = int(os.environ.get("DG_PER_AGENT_HARD_CAP_SEC", "5400"))' in src
    assert "_hit_hard_cap = elapsed >= PER_AGENT_HARD_CAP_SEC" in src


# ------------------------ the assumption the whole fix rests on, exercised


class _Page:
    async def evaluate(self, *a, **k):
        return None

    async def screenshot(self, **k):
        return b""


def _cua_forbidden(*a, **k):
    raise AssertionError(
        "a CUA tier ran on a page the caller said was frozen — the "
        "browser=None / cua_client=None switch no longer disables it"
    )


def test_chatgpt_runs_no_cua_tier_when_it_is_handed_none(monkeypatch):
    """⭐ THE LOAD-BEARING ASSUMPTION. The fix disables the expensive tiers by
    withholding the browser and the CUA client, which only works while every one
    of those tiers is gated on them. Asserted by running the real extractor with
    every CUA entry point booby-trapped."""
    monkeypatch.setattr(research, "_extract_via_cua_download", _cua_forbidden)
    monkeypatch.setattr(research, "_run_with_clipboard_hijack", _cua_forbidden)
    monkeypatch.setattr(research, "agent_loop", _cua_forbidden)

    async def _no_dom(*a, **k):
        return ""

    monkeypatch.setattr(research, "_extract_html_to_md_anyframe", _no_dom)
    _real = asyncio.sleep
    monkeypatch.setattr(research.asyncio, "sleep", lambda *_a, **_k: _real(0))

    assert asyncio.run(research.extract_chatgpt_response(
        _Page(), browser=None, cua_client=None, label="ChatGPT")) == ""


def test_chatgpt_does_run_its_cua_tier_when_it_is_handed_one(monkeypatch):
    """⛔ The other half. If the expensive tiers had quietly stopped running for
    everyone, the test above would pass while the fix did nothing — and every
    healthy scrape-blind agent would lose its report."""
    monkeypatch.setattr(research, "_extract_via_cua_download", _cua_forbidden)
    _real = asyncio.sleep
    monkeypatch.setattr(research.asyncio, "sleep", lambda *_a, **_k: _real(0))
    with pytest.raises(AssertionError, match="a CUA tier ran"):
        asyncio.run(research.extract_chatgpt_response(
            _Page(), browser=object(), cua_client=object(), label="ChatGPT"))


def guarded_cua_calls(fn):
    """CUA entry points inside `fn` that are NOT under an `if` mentioning both
    `browser` and `cua_client`, walked with the guard stack carried down."""
    tree = ast.parse(inspect.getsource(fn))
    unguarded = []

    def names(node):
        return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}

    def walk(node, guarded):
        # The node ITSELF has to be tested, not only its children — an `if`
        # reached as a statement inside another `if`'s body arrives here as the
        # node, and an earlier draft that only inspected children marked every
        # properly-guarded call in Claude's extractor as unguarded.
        if isinstance(node, ast.If):
            inner = guarded or {"browser", "cua_client"} <= names(node.test)
            for stmt in node.body:
                walk(stmt, inner)
            for stmt in node.orelse:
                walk(stmt, guarded)
            return
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", "") in
                ("agent_loop", "_extract_via_cua_download")
                and not guarded):
            unguarded.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            walk(child, guarded)

    walk(tree, False)
    return unguarded


@pytest.mark.parametrize("fn", [
    research.extract_chatgpt_response,
    research.extract_claude_response,
    research.extract_gemini_response,
])
def test_every_cua_tier_is_gated_on_the_browser_and_the_client(fn):
    """The same assumption for the two agents whose extractors are too
    entangled to drive end to end here. An ungated CUA mission would keep
    running on a frozen page and the fix would silently stop working for that
    agent only."""
    assert guarded_cua_calls(fn) == [], (
        f"{fn.__name__} runs a CUA mission that browser=None cannot disable "
        f"(line offsets {guarded_cua_calls(fn)})"
    )
