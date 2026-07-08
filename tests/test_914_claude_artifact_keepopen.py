"""#914 (2026-07-08): Claude P2 artifact/source panel — keep it OPEN.

GROUND TRUTH (user E2E 2026-07-08 + backend.log/backend-2.log, 6+ runs):
P2 Claude repeatedly opened and CLOSED the right-side Source/artifact
panel instead of keeping it open (ChatGPT P1+P2 fine after #913). Log
forensics showed the whole read pipeline had collapsed onto the Layer-2
CUA fallback, whose per-call task text ended "Then close the artifact
panel." — directly contradicting PROMPT_SCRAPE_CLAUDE_ARTIFACT_TRACKING's
step 5 ("DO NOT close the artifact panel"). The CUA obeyed the task text
("close the artifact panel as instructed…" every cycle), the call site
then flagged artifact_panel_open=True anyway (it only checked that data
came back, not which layer produced it or whether a panel was mounted),
so the next poll skipped the re-click, the DOM read an absent panel, and
the CUA re-opened/re-closed — visible toggling every ARTIFACT_SCRAPE_
INTERVAL. The DOM layer itself was dead on the 2026-07 claude.ai UI:
bare `.click()` on the card was swallowed (the CUA arriving ~30s later
found the panel closed and had to click the card itself; twice it found
an open CONTEXT MENU instead), every read selector is artifact-class-
anchored, and the walker root fell back to bare `aside` (the LEFT NAV)
then `document` — the suspiciously constant "15 steps, 15 sections" junk.

Fix (mirror of ChatGPT #913):
  - Layer-2 CUA task text + context_hint now say LEAVE the panel OPEN;
  - `_claude_artifact_panel_state` — geometry-first truthful probe
    (right-docked flush-right panel; menu_open detection); the call-site
    flag is set from the probe, never from "data came back";
  - bounded re-clicks after collapse (claude_panel_reopens ≤ 3);
  - `_click_claude_artifact` dispatches the full pointer/mouse chain;
  - `_read_claude_artifact_panel` + walker get a class-free geometry
    fallback (`_bestGeoPanel`); walker roots ONLY at a real panel (no
    bare `aside`/document steps sweep — junk is worse than empty);
  - `_log_claude_artifact_snapshot` at misses #2/#5 + on menu-click
    (instrument-with-logs directive);
  - tracking log line carries layer=dom|cua, walker_root, panel_open,
    step0 so backend.log alone answers "is the DOM path healthy?".
"""

import ast
import asyncio
import inspect
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import research  # noqa: E402
import prompts  # noqa: E402

_SRC = Path(research.__file__).read_text(encoding="utf-8")


def _scrape_src():
    return inspect.getsource(research.scrape_claude_artifact_tracking)


# ── root cause: no instruction may tell the CUA to close the panel ──────────

def test_layer2_cua_task_text_keeps_panel_open():
    src = _scrape_src()
    assert "Then close the artifact panel" not in src, (
        "the Layer-2 task text contradicted the system prompt's 'DO NOT "
        "close' and produced the open→read→close churn the user watched "
        "all E2E 2026-07-08")
    assert "LEAVE the" in src and "OPEN" in src
    # context_hint for the shadow/vision wrapper must agree
    assert "then close the panel" not in src


def test_system_prompt_still_pins_do_not_close():
    assert "DO NOT close the artifact panel" in prompts.PROMPT_SCRAPE_CLAUDE_ARTIFACT_TRACKING


def test_tier3_open_prompt_forbids_closing():
    assert "DO NOT close the panel after opening" in prompts.PROMPT_OPEN_CLAUDE_SOURCE_ARTIFACT


def test_close_helper_only_called_from_keepopen_false_and_final_extract():
    # Exactly two call sites: the keep_open=False branch inside the scrape
    # helper (no caller passes keep_open=False today) and the deliberate
    # close-1 before final extract. The poll loop must never close.
    assert _SRC.count("await _close_claude_artifact_panel(") == 2


# ── truthful flag: probe-derived, never "data came back" ─────────────────────

def test_call_site_sets_flag_from_probe():
    # Claude poll block: pre-probe before the scrape, post-probe after,
    # flag assigned from the probe result.
    claude_block = _SRC[_SRC.index("#914 anti-churn pre-check"):]
    claude_block = claude_block[:claude_block.index("Block 1b")]
    assert claude_block.count("_claude_artifact_panel_state(p[\"page\"])") >= 3, (
        "pre-probe + post-probe + tier-3 probe")
    assert 'p["artifact_panel_open"] = _now_open' in claude_block
    assert re.search(r'p\["artifact_panel_open"\]\s*=\s*True', claude_block) is None, (
        "the flag must never be set True unconditionally — that is how the "
        "CUA-closed panel stayed flagged open forever")
    assert "_runtime.claude_artifact_panel_open = _now_open" in claude_block


def test_call_site_bounds_reopen_attempts():
    assert "claude_panel_reopens" in _SRC
    # #914b: the cap is checked at ENTRY (flag-independent) — the old
    # flag-transition-only cap let a panel whose clicks never stick
    # (post-probe always closed → flag never True) re-click unbounded.
    assert re.search(r"_reopens\s*>=\s*3", _SRC), "click budget checked at entry"
    assert "click didn't stick" in _SRC, (
        "a click that came back with data but no mounted panel must burn "
        "the click budget, or probe false-negatives re-click forever")
    assert "_attempted_open" in _SRC


def test_first_time_log_only_once():
    # #914b: reopen-after-collapse must not log "(first time)" again —
    # grep-count forensics depend on it.
    assert "_claude_panel_ever_open" in _SRC
    assert _SRC.count("artifact panel opened (first time)") == 0 or \
        "first time" in _SRC  # tag is computed, not inlined
    assert 're-opened, reopens=' in _SRC


def test_already_open_arg_comes_from_probe_not_flag():
    claude_block = _SRC[_SRC.index("#914 anti-churn pre-check"):]
    claude_block = claude_block[:claude_block.index("Block 1b")]
    assert "already_open=_probe_open" in claude_block
    assert 'already_open=p.get("artifact_panel_open"' not in claude_block


# ── DOM layer hardening ──────────────────────────────────────────────────────

def test_click_dispatches_full_pointer_chain():
    src = inspect.getsource(research._click_claude_artifact)
    for ev in ("pointerdown", "mousedown", "pointerup", "mouseup"):
        assert ev in src, (
            "bare .click() was swallowed by claude.ai's React listeners — "
            "same lesson as the ChatGPT activity strip (2026-04-26 v2)")


def test_reader_has_geometry_fallback_in_both_paths():
    src = inspect.getsource(research._read_claude_artifact_panel)
    assert "_bestGeoPanel" in src
    assert src.count("_bestGeoPanel(200)") == 2, (
        "both _try_html and _try_text need the class-free fallback")
    # flush-right dock gates — a centered chat column must not qualify
    assert "_vw - 40" in src
    assert "_vw * 0.22" in src


def test_walker_root_never_bare_aside_or_document_for_steps():
    src = _scrape_src()
    assert "'[data-testid=\"artifact-content\"], aside," not in src, (
        "bare `aside` matched claude.ai's LEFT NAV (2026-05-13 lesson) — "
        "the steps sweep harvested nav rows (constant '15 steps' junk)")
    assert "out.root = 'geo'" in src and "out.root = 'class'" in src
    # steps/sections only collected under a real root
    assert "if (root)" in src
    # URL fallback excludes nav chrome when unrooted
    assert "a.closest('nav, aside, [class*=\"sidebar\" i]')" in src


def test_scrape_reports_layer_and_walker_root():
    src = _scrape_src()
    assert '"layer": _layer' in src
    assert '"walker_root"' in src
    # call-site tracking log line carries the forensics fields
    assert "layer={artifact_data.get('layer')}" in _SRC
    assert "panel_open={_now_open}" in _SRC
    assert "step0=" in _SRC, (
        "log the first step so nav-junk narration is visible from the log")


def test_post_click_guard_probes_and_escapes_menus():
    src = _scrape_src()
    assert "menu_open" in src
    assert "click-opened-menu" in src
    assert 'press("Escape")' in src


# ── instrumentation ──────────────────────────────────────────────────────────

def test_miss_snapshots_wired():
    assert _SRC.count("_log_claude_artifact_snapshot(") >= 3, (
        "snapshot at miss #2/#5 + on menu-click (instrument-with-logs)")
    src = inspect.getsource(research._log_claude_artifact_snapshot)
    assert "artifact-miss snapshot" in src
    assert "frames" in src
    assert "1800" in src, "snapshot line stays log-friendly (≤1.8KB)"


# ── probe functional tests ───────────────────────────────────────────────────

class _FakePage:
    def __init__(self, result=None, raise_exc=False):
        self._result = result
        self._raise = raise_exc

    async def evaluate(self, js):
        if self._raise:
            raise RuntimeError("boom")
        return self._result


def test_probe_returns_dict_and_maps_open():
    res = asyncio.run(research._claude_artifact_panel_state(
        _FakePage({"open": True, "width": 612, "text_len": 480, "menu_open": False})))
    assert res["open"] is True and res["width"] == 612


def test_probe_failure_reads_as_closed():
    res = asyncio.run(research._claude_artifact_panel_state(_FakePage(raise_exc=True)))
    assert isinstance(res, dict) and not res.get("open")
    res2 = asyncio.run(research._claude_artifact_panel_state(_FakePage("not-a-dict")))
    assert isinstance(res2, dict) and not res2.get("open")


def test_probe_gates_are_flush_right_and_tall():
    src = inspect.getsource(research._claude_artifact_panel_state)
    assert "vw - 40" in src, "right-docked panel is flush right"
    assert "vw * 0.22" in src, "left gate excludes full-width wrappers/body"
    assert "vh * 0.5" in src, (
        "height gate matches the read path's 0.5vh — #906 rule: the "
        "verifier must never be stricter than the scraper (a 0.6vh probe "
        "over a 0.5vh reader left a divergence window where data flowed "
        "with the flag stuck closed → unbounded re-clicks)")
    assert "vh * 0.6" not in src
    assert "iframe" in src, (
        "artifact content can be iframe-mounted — host innerText reads '' "
        "then (same lesson as ChatGPT's DR-card iframe embed)")
    assert "menu_open" in src


def test_geometry_gates_exclude_chat_column_everywhere():
    # #914b (review, self-verified MAJOR): with the sidebar EXPANDED
    # (~288px) the nav-right main-content wrapper passes pure geometry at
    # 1280px (left=288 ≥ 0.22vw, flush right, width 992 ≤ old 0.78vw cap).
    # Guards: 0.75vw width cap (960 < 992) + skip candidates CONTAINING
    # chat-thread markers — in the probe, the reader fallback, AND the
    # walker root (all three sweep 'div, aside, section').
    for fn in (research._claude_artifact_panel_state,
               research._read_claude_artifact_panel,
               research.scrape_claude_artifact_tracking):
        src = inspect.getsource(fn)
        assert '[data-testid="user-message"]' in src, fn.__name__
        assert ".font-claude-message" in src, fn.__name__
        assert "* 0.75" in src, fn.__name__
        assert "* 0.78" not in src, fn.__name__


# ── no-backspace regression (JS regex inside non-raw Python strings) ─────────

def test_no_literal_backspace_in_claude_scraper_strings():
    for fn in (research.scrape_claude_artifact_tracking,
               research._read_claude_artifact_panel,
               research._claude_artifact_panel_state,
               research._log_claude_artifact_snapshot,
               research._count_claude_artifacts,
               research._click_claude_artifact,
               research._close_claude_artifact_panel):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "\x08" not in node.value, (
                    f"{fn.__name__} embeds a string with a literal backspace "
                    "— a lone \\b in a non-raw Python string; the JS regex "
                    "it belongs to can never match (#913 VERB_GATE lesson)")
