"""#913 (2026-07-07): ChatGPT 2026-07 UI — shape-agnostic activity open +
rich source-panel relay.

GROUND TRUTH (user screenshot 2026-07-07 + backend.log 2026-07-06, 4 runs):
clicking the shimmering status line below the sent message OPENS a right-
side panel headed "Activity · <N>s" in P1 — but it is NARROW (~21% of the
viewport ≈ 267px at our 1280px viewport) and shows only skeleton rows early
(~33 chars), so the old verifier's ≥280px width + ≥50-char text gates
rejected the OPEN panel, judged the click failed, and re-clicked the toggle
every ~30s — closing it. In P2, the DR card renders inside an iframe whose
URL no longer matches "deep_research|oaiusercontent" (walked_hits=0 on every
cycle while CUA could SEE the strip; CUA's one success opened the "Deep
research execution plan" side panel). Completed strips are not clickable.

Fix:
  - `_CHATGPT_SIDE_PANEL_JS` Signature A: "Activity"-headed right-side
    container, no text floor (skeleton-only = open); legacy sweep width
    gate 280→240;
  - structural PASS 0 in the opener: the shimmering status line directly
    below the last SENT (user) message — position + interactivity + shimmer
    animation, never wording (user directive: the text mutates with the
    platform's progress);
  - every ChatGPT frame walk enumerates ALL frames (no URL filter);
  - `_chatgpt_activity_state` = shape-agnostic open detector, used BEFORE
    clicking (anti-toggle — the line is a toggle) and as the verify;
  - `scrape_chatgpt_activity_panel_tracking` (Activity-root preferred,
    width gate 200, inline-turn fallback) + `scrape_progress_chatgpt`
    (per-cycle turn sweep) keep narration rich for P1 and P2;
  - VERB_GATE backspace fix: a lone \\b in a NON-raw Python string parsed
    to a literal backspace, so the panel walker's step gate NEVER matched
    since it shipped;
  - persistent misses log a compact DOM snapshot (instrument-with-logs
    directive) so the next miss is root-causable from backend.log alone.
"""

import asyncio
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import research  # noqa: E402
import prompts  # noqa: E402

_SRC = Path(research.__file__).read_text(encoding="utf-8")


# ── opener: structural anchor + all-frames ──────────────────────────────────

def test_opener_has_structural_pass0():
    src = inspect.getsource(research._open_chatgpt_activity_panel)
    assert "PASS 0" in src and "STRUCTURAL" in src
    assert 'data-message-author-role="user"' in src, (
        "PASS 0 must anchor on the last SENT (user) message — the status "
        "line sits directly below it and its wording mutates with progress")
    assert "picked.anchor = 'structural'" in src
    # never click bare prose: candidates need interactivity or shimmer
    assert "animationName" in src and "backgroundClip" in src
    assert "tabindex" in src.lower()
    # composer/header/toolbar subtrees excluded from candidates
    assert "composer" in src and "toolbar" in src


def test_opener_structural_pass_has_escape_hatch():
    src = inspect.getsource(research._open_chatgpt_activity_panel)
    assert "skipStructural" in src and "skip_structural" in src
    # both call sites disable PASS 0 after 2 misses so a host-page
    # false-positive can't starve the legacy passes + frame walk forever
    assert _SRC.count("skip_structural=(") == 2


def test_opener_keeps_legacy_wording_anchors():
    # PASS 1/2 fallbacks still serve the DR count-badge strip.
    src = inspect.getsource(research._open_chatgpt_activity_panel)
    assert "STATUS_LINE" in src and "hasStatusLine" in src
    assert "citations?" in src
    assert "ELLIPSIS" in src


def test_opener_walks_all_frames_not_url_filtered():
    src = inspect.getsource(research._open_chatgpt_activity_panel)
    assert '"deep_research" in' not in src and '"oaiusercontent" in' not in src, (
        "the DR card's iframe URL no longer matches any fixed substring — "
        "URL-filtering frames is how walked_hits=0'd every P2 cycle live "
        "2026-07-06")
    assert "main_frame" in src
    assert "frameUrl" in src, "successful frame hits must be attributable in logs"


# ── shape-agnostic state probe + verify ──────────────────────────────────────

def test_state_probe_checks_both_shapes_and_frames():
    src = inspect.getsource(research._chatgpt_activity_state)
    assert "_CHATGPT_SIDE_PANEL_JS" in src
    assert "_CHATGPT_INLINE_ACTIVITY_JS" in src
    assert "main_frame" in src, "the DR side panel can mount inside the iframe"


def test_verify_is_shape_agnostic():
    src = inspect.getsource(research._verify_chatgpt_panel_open)
    assert "_chatgpt_activity_state" in src
    assert "inline_expanded" in src and "side_panel" in src


class _FakePage:
    """page.evaluate keyed by which module-level JS constant it receives."""

    def __init__(self, side=False, inline=None):
        self._side = side
        self._inline = inline
        self.frames = []
        self.main_frame = None

    async def evaluate(self, js):
        if js is research._CHATGPT_SIDE_PANEL_JS:
            return self._side
        if js is research._CHATGPT_INLINE_ACTIVITY_JS:
            return self._inline
        return None


def test_state_probe_reports_inline_drawer():
    page = _FakePage(side=False, inline={"expanded": True, "partial_text_len": 4321})
    st = asyncio.run(research._chatgpt_activity_state(page))
    assert st["side_panel"] is False
    assert st["inline_expanded"] is True
    assert st["thread_len"] == 4321
    assert asyncio.run(research._verify_chatgpt_panel_open(page)) is True


def test_state_probe_reports_closed():
    page = _FakePage(side=False, inline={"expanded": False, "partial_text_len": 10})
    st = asyncio.run(research._chatgpt_activity_state(page))
    assert st["side_panel"] is False and st["inline_expanded"] is False
    assert asyncio.run(research._verify_chatgpt_panel_open(page)) is False


def test_state_probe_side_panel_wins():
    page = _FakePage(side=True, inline=None)
    st = asyncio.run(research._chatgpt_activity_state(page))
    assert st["side_panel"] is True
    assert asyncio.run(research._verify_chatgpt_panel_open(page)) is True


# ── anti-toggle: never click while a shape is open ──────────────────────────

def test_both_call_sites_precheck_state_before_clicking():
    assert _SRC.count("#913 anti-toggle") == 2, (
        "P1 poll AND P2 round-robin must both pre-check "
        "_chatgpt_activity_state before _open_chatgpt_activity_panel — the "
        "status line is a TOGGLE; blind re-clicks close the drawer")
    for block in _SRC.split("#913 anti-toggle")[1:]:
        head = block[:2000]
        pre = head.find("_chatgpt_activity_state(")
        clk = head.find("_open_chatgpt_activity_panel(")
        assert pre != -1 and clk != -1 and pre < clk, (
            "state pre-check must run BEFORE the click in each call site")


def test_p1_reopen_is_bounded():
    assert "_panel_reopens" in _SRC
    assert "_panel_reopens <= 3" in _SRC, (
        "drawer auto-collapse re-opens must be bounded — unbounded re-open "
        "is the toggle storm again with extra steps")


# ── scrapers: inline shape + all frames ──────────────────────────────────────

def test_tracking_scraper_reads_inline_and_all_frames():
    src = inspect.getsource(research.scrape_chatgpt_activity_panel_tracking)
    assert "_CHATGPT_INLINE_ACTIVITY_JS" in src
    assert "panel_shape" in src
    assert '"deep_research" in' not in src, "frame walk must not be URL-filtered"
    assert "main_frame" in src


def test_progress_scraper_sweeps_inline_every_cycle():
    src = inspect.getsource(research.scrape_progress_chatgpt)
    assert "_CHATGPT_INLINE_ACTIVITY_JS" in src, (
        "P1 narration must stay rich from the first poll tick — the status "
        "line + counts are scrapeable even with the drawer collapsed")
    assert "status_line" in src


def test_inline_js_covers_the_relay_fields():
    js = research._CHATGPT_INLINE_ACTIVITY_JS
    for field in ("steps", "source_urls", "sections", "searches",
                  "partial_text_len", "status_line", "expanded"):
        assert field in js, f"inline walker must produce `{field}`"
    assert "citations?" in js, "counts regex must include the citations badge"
    assert "aria-expanded" in js
    assert "url=" in js, "chatgpt.com redirector unwrap required for source chips"


def test_et_fallback_never_clobbers_scraped_status_line():
    assert "#913: the inline-activity sweep" in _SRC, (
        "the generic 'Extended Thinking active' fallback must yield to the "
        "scraped live status line")


# ── instrumentation (instrument-with-logs directive) ─────────────────────────

def test_miss_snapshots_wired_at_both_sites():
    assert _SRC.count("_log_chatgpt_thread_snapshot") >= 5, (
        "def + P1 miss sites + P2 miss sites — persistent misses must dump "
        "a compact DOM snapshot so the next UI drift is root-causable from "
        "backend.log alone (no out-of-band browser probing on the worker "
        "profile — bot-score risk)")
    src = inspect.getsource(research._log_chatgpt_thread_snapshot)
    assert "frames" in src, "frame inventory answers 'which iframe is the DR card in'"
    assert "anim" in src and "btn" in src


def test_open_success_logs_shape_anchor_frame():
    for marker in ("shape={_shape}", "anchor={res.get('anchor'"):
        assert _SRC.count(marker) >= 2, (
            f"open-success log must carry {marker} in both P1 and P2 sites")


# ── ground truth: the P1 "Activity" panel (user screenshot 2026-07-07) ──────

def test_side_panel_js_has_activity_signature():
    js = research._CHATGPT_SIDE_PANEL_JS
    assert "activity" in js and "Signature A" in js, (
        "the P1 panel is headed 'Activity · Ns' — the header anchor is the "
        "strongest signature and carries no text-length floor")
    assert "r.width < 240" in js and "r.width < 280" not in js, (
        "the Activity panel is ~267px at a 1280px viewport — a 280px gate "
        "rejects the OPEN panel and restarts the toggle storm")


def test_side_panel_js_no_raw_backspace():
    # lone \b in a NON-raw Python string parses to a literal backspace and
    # silently kills the JS regex (the VERB_GATE bug lived for months).
    for name in ("_CHATGPT_SIDE_PANEL_JS", "_CHATGPT_INLINE_ACTIVITY_JS"):
        assert "\x08" not in getattr(research, name), f"{name} has a raw backspace"


def test_no_raw_backspace_in_chatgpt_scraper_literals():
    import ast
    import textwrap
    for fn in (research.scrape_chatgpt_activity_panel_tracking,
               research.scrape_progress_chatgpt,
               research._open_chatgpt_activity_panel,
               research._log_chatgpt_thread_snapshot,
               research._chatgpt_activity_state):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "\x08" not in node.value, (
                    f"{fn.__name__} embeds a string with a literal backspace "
                    "— a lone \\b in a non-raw Python string; the JS regex "
                    "it belongs to can never match")


def test_tracking_scraper_prefers_activity_root():
    src = inspect.getsource(research.scrape_chatgpt_activity_panel_tracking)
    assert "activityRoot" in src
    assert "activityRoot || panels[0]" in src, (
        "the Activity-headed root must beat the height-ranked legacy match")
    assert "r.width >= 200" in src, (
        "panel filter must admit the ~267px Activity panel")


# ── CUA prompt: real shapes are success ──────────────────────────────────────

def test_cua_prompt_matches_ground_truth():
    p = prompts.PROMPT_OPEN_CHATGPT_SOURCE_PANEL
    assert "Activity" in p and "skeleton" in p.lower(), (
        "CUA must accept the narrow skeleton-only Activity panel as OPEN — "
        "live 2026-07-06 it kept reporting 'no side panel slid out'")
    assert "inline thoughts/activity" in p
    assert "IT IS A TOGGLE" in p
    assert "DIRECTLY BELOW" in p, (
        "2026-07 UI: early in a response the status line sits directly "
        "below the last sent message")
    assert "Answer now" in p, (
        "'Answer now' inside the Activity panel truncates the run — CUA "
        "must never click it")
    # already-open detection must include the skeleton/inline shapes
    assert p.count("panel: already_open") >= 2
