"""Claude: don't call an unsent research "generating", and tag retries correctly.

`verify_claude_generating` had no URL gate, so it returned True off any button whose
label merely contained "stop" or any visible running animate/spin/pulse animation. On
2026-07-27 it logged `[2B] ✓ Verified — actively generating` at 22:46:04 and the system
reported the agent healthy for 8m18s while claude.ai sat on https://claude.ai/new
behind a "We couldn't connect to Claude" banner with brief.md still unsent — `frames`
on /new, `text_len` pinned at exactly 74, sources=0, steps=0. Only a CUA screenshot
eventually caught it, by which point the agent had been dropped from rotation.

The panel-selector work that once lived here (rename-chat rejection, the "View <title>"
document-artifact selector, the exclude_opener threading, the sources toggle) was
deliberately REVERTED. It reached into `_count_claude_artifacts` /
`_click_claude_artifact`, which feed extraction, publish, the poll loop AND two count
gates, and the live e2e showed the panel opening healthily at cycle 3 without any of it.
The defect it addressed costs degraded telemetry on roughly one run in twenty-one — not
worth that blast radius alongside the fixes actually asked for. The live DOM findings
are recorded in memory if it is ever re-added, as one isolated change.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import re

research = importlib.import_module("research")


# ── the URL gate ───────────────────────────────────────────────────────────

class _FakePage:
    """Minimal Playwright-page stand-in. `dom_says_generating` models the OLD
    predicate: an animation/stop-button hit that says nothing about a send landing."""

    def __init__(self, url, dom_says_generating=True):
        self.url = url
        self._dom = dom_says_generating
        self.evaluated = 0

    async def evaluate(self, js, *a):
        self.evaluated += 1
        if "scrollTo" in js:
            return None
        return self._dom


def _verify(url, dom=True):
    page = _FakePage(url, dom)
    return asyncio.run(research.verify_claude_generating(page)), page


class TestClaudeConversationUrlGate:
    def test_new_tab_is_not_generating_even_when_the_dom_says_so(self):
        """The exact 2026-07-27 state: still on /new, DOM animation present."""
        ok, page = _verify("https://claude.ai/new", dom=True)
        assert ok is False, (
            "reported generating while the tab was still on /new — nothing was sent"
        )
        assert page.evaluated == 0, "must short-circuit before probing the DOM"

    def test_root_and_chat_list_are_not_conversations(self):
        for u in ("https://claude.ai", "https://claude.ai/", "https://claude.ai/chats",
                  "https://claude.ai/new?foo=1", "https://claude.ai/new#x"):
            ok, _ = _verify(u, dom=True)
            assert ok is False, u

    def test_a_real_conversation_still_uses_the_dom_probe(self):
        ok, page = _verify("https://claude.ai/chat/ff7f7e04-ed8e-490e-a307-ca0c2f079045")
        assert ok is True and page.evaluated > 0

    def test_a_real_conversation_that_is_idle_reads_false(self):
        # The gate must not turn into a rubber stamp: on a conversation URL the DOM
        # probe is still authoritative.
        ok, _ = _verify("https://claude.ai/chat/abc", dom=False)
        assert ok is False

    def test_unreadable_url_falls_back_to_the_dom_probe(self):
        # A measurement failure must not gate the send/verify path.
        class _Boom:
            @property
            def url(self):
                raise RuntimeError("detached")

        assert research._claude_conversation_url(_Boom()) is True

    def test_project_conversations_count(self):
        assert research._claude_conversation_url(
            _FakePage("https://claude.ai/project/xyz/chat/1")) is True


# ── the retry-tag transposition ────────────────────────────────────────────

def test_retry_tags_match_the_canonical_agent_letters():
    """Canonical from run_phase2's own headers: 2A=ChatGPT, 2B=Claude, 2C=Gemini.
    `_restart_phase2_agent` had Claude→2C-retry and Gemini→2B-retry, so grepping
    [2B] for a Claude retry silently dropped all 11 of its lines and [2C] returned
    Claude lines that navigate to claude.ai."""
    src = inspect.getsource(research._restart_phase2_agent)
    for agent, tag, url_frag in (("ChatGPT", "2A-retry", "chatgpt.com"),
                                 ("Claude", "2B-retry", "claude.ai"),
                                 ("Gemini", "2C-retry", "gemini.google.com")):
        blk = src[src.index(f'if name == "{agent}":'):]
        blk = blk[:blk.index("return (new_page,")]
        assert url_frag in blk, f"{agent} block not located"
        assert f'"{tag}"' in blk, f"{agent} must be tagged {tag}, got: {set(re.findall(r'2[A-D]-retry', blk))}"
        for other in ("2A-retry", "2B-retry", "2C-retry"):
            if other != tag:
                assert f'"{other}"' not in blk, f"{agent} block also carries {other}"


# ── the reverted panel work must stay reverted ─────────────────────────────

def test_the_artifact_helpers_were_left_alone():
    """Guard the scope decision itself. `_count_claude_artifacts` and
    `_click_claude_artifact` feed extraction, publish, the poll loop AND two count
    gates — the widest blast radius in the Claude path. A future change there should be
    deliberate and isolated, never a passenger on an unrelated fix."""
    for fn in (research._count_claude_artifacts, research._click_claude_artifact):
        src = inspect.getsource(fn)
        assert "exclude_opener" not in src, f"{fn.__name__} regained the flag"
        assert "rename chat" not in src, f"{fn.__name__} regained the rename guard"
        assert "research panel" not in src, f"{fn.__name__} regained the panel selector"
    assert not hasattr(research, "_click_claude_sources_toggle"), (
        "the sources-toggle helper came back"
    )


# ── warm-tab reuse must survive a drop-from-rotation ──────────────────────────

def test_pre_pending_stub_recovers_the_still_open_tab():
    """Gap #3 reuses the warm, challenge-passed tab on a hard retry — every cold
    top-level load is a Cloudflare bot-score event, the same cost that made P1 and P2
    share one ChatGPT tab. But reuse keys on p["page"], and an agent DROPPED from
    rotation has no `pending` entry, so the stub used to seed "page": None and force a
    cold load. The dropped agent's page IS preserved in results[name]["page"] and is
    never closed, so recover it."""
    src = inspect.getsource(research.poll_all_agents_round_robin)
    blk = src[src.index("failed pre-pending") - 1600:]
    blk = blk[:blk.index('"hard_retry_count": 0')]
    assert "results.get(_agent_name)" in blk, (
        "the stub must try to recover the dropped agent's still-open page"
    )
    assert "is_closed()" in blk, "…and must never hand back a dead page"
    assert '"page": _stub_page' in blk, '"page": None would defeat warm-tab reuse'
    # The clean-slate escape hatch on hard retry #2 must remain.
    assert "_hard_count < 2" in src
