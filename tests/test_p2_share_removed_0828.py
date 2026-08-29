"""The P2 platform share step is gone, and these are the things that must not
have gone with it.

WHAT WAS REMOVED (stretch 6.6B, 2026-08-28)

Phase 2 ran three platform share-link extractors after every agent finished —
ChatGPT's Share modal, Gemini's share dialog, Claude's artifact Publish flow —
plus a CUA fallback for each. Measured cost: 2.2 minutes and 21.7 CUA calls per
run, 31% of every CUA call the pipeline makes.

⭐ AND NOTHING GATED ON THE RESULT. Phase 2's completion gate is `n_chars > 0 and
md_saved`; the extractors' output went into `links.{chatgpt,gemini,claude}` and
`_runtime.agent_share_urls`, both consumed only by delivery. Phase 5 now
delivers Super Research's own `/shared/doc/{id}` snapshot pages, minted from the
markdown already in Firestore — which work for a reader who is not the owner,
where half the corpus's "share" links were the private conversation URL fallback.

⛔⛔ WHAT THESE TESTS ARE FOR. A 1,500-line removal from a 76k-line file is
mostly invisible: the interesting failures are the things that were TANGLED with
it. Four of them are pinned below, and each one is a specific way the removal
could have taken something with it.
"""
import ast
import inspect
import re

import pytest

import research
import prompts
from conftest import code_only, code_only_deep


@pytest.fixture(scope="module")
def src() -> str:
    return code_only_deep(inspect.getsource(research))


# ── 1. the removed surface is actually gone, by name ────────────────────────

REMOVED = (
    "extract_share_link_chatgpt",
    "extract_share_link_gemini",
    "extract_share_link_claude",
    "_gemini_share_closer",
    "publish_open_claude_artifact",
    "_extract_claude_via_published_page",
    "_close_chatgpt_canvas",
    "_CANVAS_ROOT_SELECTORS",
    "_CANVAS_CLOSE_MARK",
    "_CANVAS_PROBE_JS",
    "_CANVAS_MARK_CLOSE_JS",
    "_PUBLIC_SHARE_SHAPES",
    "_PUBLIC_SHARE_EXPECTED",
    "_public_share_is_expected",
    "_is_public_share_url",
)


@pytest.mark.parametrize("name", REMOVED)
def test_the_symbol_is_gone_from_the_module(name):
    assert not hasattr(research, name), f"{name} is still importable"


@pytest.mark.parametrize("name", REMOVED)
def test_the_symbol_is_not_referenced_anywhere_in_the_source(name, src):
    """⛔ A NAME LEFT IN A CALL IS A NameError AT RUN TIME, NOT AT IMPORT TIME.
    `hasattr` above only proves the def went; this proves nothing still calls
    it. Comments are blanked, so the prose recording the removal does not
    satisfy the check — that is the exact trap `code_only` exists for."""
    assert name not in src, f"{name} is still referenced in research.py"


@pytest.mark.parametrize("name", (
    "PROMPT_SHARE_GEMINI", "PROMPT_PUBLISH_CLAUDE", "PROMPT_PUBLISH_CLAUDE_ARTIFACT",
))
def test_the_share_prompts_are_gone(name):
    assert not hasattr(prompts, name), f"{name} survives in prompts.py"
    assert name not in code_only_deep(inspect.getsource(research)), name


def test_the_prompts_section_header_no_longer_promises_shareable_links():
    """⛔ The header above the two removed prompts read 'Phase 3: Shareable
    Links + NotebookLM' — a phase they never ran in (both were consumed in
    Phase 2) and a subject that no longer exists. It now sits over
    PROMPT_NOTEBOOKLM_UPLOAD alone."""
    text = inspect.getsource(prompts)
    assert "Shareable Links" not in text
    assert "# ── Phase 3: NotebookLM" in text


# ── 2. the hotspots go from BOTH tables ─────────────────────────────────────

@pytest.mark.parametrize("hotspot", ("p2-share", "publish-claude"))
def test_the_share_hotspots_are_gone_from_both_tables(hotspot, src):
    """⛔ TWO TABLES, NOT ONE. `_HOTSPOT_TO_OP` drives tier-transition
    telemetry and `_HOTSPOT_VISION_HINTS` drives the vision prompt; a row left
    in either is an id that can never fire and a name a reader will hunt for."""
    assert hotspot not in research._HOTSPOT_TO_OP
    assert hotspot not in research._HOTSPOT_VISION_HINTS
    assert f'hotspot_id="{hotspot}"' not in src


# ── 3. ⛔⛔ WHAT MUST NOT HAVE GONE WITH IT ──────────────────────────────────

KEPT_MARKDOWN = (
    "extract_claude_response",
    "_read_claude_artifact_panel",
    "_looks_like_nav_sidebar",
    "_extract_html_to_md",
)


@pytest.mark.parametrize("name", KEPT_MARKDOWN)
def test_the_markdown_extractors_around_the_cut_survived(name):
    """⛔⛔ THE CUTS RAN THROUGH CLAUDE'S MARKDOWN CODE. The dead
    `_extract_claude_via_published_page` sat BETWEEN `_read_claude_artifact_panel`
    and `_looks_like_nav_sidebar` with one blank line on either side, and
    `publish_open_claude_artifact` began two lines after `extract_claude_response`
    ended. A range off by three lines in either direction would have deleted the
    report reader rather than the share step — which is silent, because a report
    that fails to extract looks exactly like an agent that produced nothing."""
    assert hasattr(research, name), f"{name} was taken by the removal"


def test_the_link_validators_still_work_for_the_platforms_that_have_one():
    """⛔⛔ THE THREE AGENT LAMBDAS CALLED THE REMOVED AUTHORITY. `_LINK_VALIDATORS`
    held `"chatgpt": lambda u: _is_public_share_url("chatgpt", u)` and two more.
    Deleting `_is_public_share_url` without them leaves a NameError that fires
    the first time anything validates a chatgpt/gemini/claude URL — inside
    `validate_link`, which is still live for NotebookLM and YouTube."""
    assert "chatgpt" not in research._LINK_VALIDATORS
    assert "gemini" not in research._LINK_VALIDATORS
    assert "claude" not in research._LINK_VALIDATORS
    # …and the ones that survive still resolve.
    assert research.validate_link("notebooklm", "https://notebooklm.google.com/notebook/abc")
    assert not research.validate_link("notebooklm", "https://notebooklm.google.com/")
    assert research.validate_link("youtube", "https://youtu.be/abc")


def test_validate_link_does_not_crash_on_a_platform_it_no_longer_knows():
    """A caller passing "chatgpt" is now asking about a platform with no
    validator. It must answer, not raise."""
    for platform in ("chatgpt", "gemini", "claude"):
        assert research.validate_link(platform, "https://chatgpt.com/share/abc") in (True, False)


def test_arm_clipboard_still_has_live_callers(src):
    """The three removed extractors were three of its callers. If the rest ever
    go, the helper becomes dead code wearing a passing test."""
    assert src.count("_arm_clipboard()") >= 2


def test_the_nlm_audio_menu_helpers_and_their_deny_list_survived():
    """⛔ `_nlm_open_audio_menu` / `_nlm_menu_pick` had TWO callers: the audio
    DOWNLOAD (kept — it produces the file P3 now completes on) and the audio
    SHARE (dropped in 6.6C). And `_NLM_MENU_DENY` exists to protect the DOWNLOAD
    caller specifically: "Delete" sits two rows below "Download"."""
    assert hasattr(research, "_nlm_open_audio_menu")
    assert hasattr(research, "_nlm_menu_pick")
    assert research._NLM_MENU_DENY, "the destructive-row deny list is empty"
    sig = inspect.signature(research._nlm_menu_pick)
    assert sig.parameters["deny"].default is research._NLM_MENU_DENY


def test_extract_with_retry_kept_its_one_live_caller(src):
    """Its only live caller is the NotebookLM notebook-link recovery, which
    stays. If that ever goes the helper is dead weight."""
    assert hasattr(research, "extract_with_retry")
    assert "extract_with_retry(" in src


# ── 4. the P2 → P3 handoff, which the removal ran straight through ──────────

def test_the_p2_to_p3_handoff_still_reads_a_url_per_agent():
    """⛔ THE ONE SILENT, HOURS-LATER FAILURE IN THE WHOLE WAVE. `links.json` is
    written at the end of P2 and its EXISTENCE is what the resume-from-Phase-3
    rung checks. The builder used to prefer `_runtime.agent_share_urls[name]`
    and fall back to the conversation URL; the preferred half is gone, so the
    fallback is now the whole answer. If that read had gone too, links.json
    would be `{}` on every run and nobody would notice until a resume."""
    src = code_only(inspect.getsource(research._build_phase2_to_phase3_handoff))
    assert 'agent_share_urls' not in src
    assert '_r.get("url")' in src
    assert "p3_links[_name] = _url" in src


def test_the_handoff_still_drops_an_off_topic_or_foreign_conversation():
    """Two guards sit between the URL and links.json, and both are about the
    conversation URL — the value that is now the ONLY source. Removing the
    share preference must not have removed them."""
    src = code_only(inspect.getsource(research._build_phase2_to_phase3_handoff))
    assert 'off_topic_rejected' in src
    assert "_chatgpt_tab_is_foreign(_url)" in src


def test_the_links_file_is_still_written_before_the_upload():
    src = code_only(inspect.getsource(research.run_phase3_upload))
    assert 'links_file.write_text' in src


# ── 5. the docstring that claimed the removal before it happened ────────────

def test_the_consumer_no_longer_claims_a_removal_that_had_not_happened():
    """⛔⛔ IT SAID SO SINCE 2026-04-25 AND IT WAS FALSE. `extract_and_record_agent`'s
    docstring read "Share-link extraction is REMOVED from P2 entirely" while
    Step 4 and Step 4b ran three extractors and a CUA fallback directly beneath
    it. An auditor reading that line concluded the work was done."""
    doc = research.extract_and_record_agent.__doc__ or ""
    assert "uses Phase 3's link extraction instead" not in doc
    assert "2026-08-28" in doc, "the docstring should say when it became true"


def test_the_consumers_post_removal_path_still_records_the_agent(src):
    """⛔ PIN THE CONSUMER, NOT THE HELPER. Step 4 was 245 lines inside
    `extract_and_record_agent`, and everything the function does for the FE
    happens before it. This asserts the surviving path, not the absence."""
    fn = code_only(inspect.getsource(research.extract_and_record_agent))
    # The in-app primary link and the terminal status are the two things the FE
    # actually consumes from this function.
    assert "emit_validated_link" in fn or "_in_app_url" in fn
    assert "_write_agent_terminal_status" in fn
    # …and the share-era variables are gone with the block.
    for gone in ("share_extractor", "share_url", "share_kind", "share_verified"):
        assert gone not in fn, f"{gone} survives in the consumer"


def test_no_agent_platform_link_is_written_to_firestore_any_more(src):
    """`update_link_in_firestore(name.lower(), share_url, …)` was the SOLE writer
    of `links.chatgpt/gemini/claude`. The frontend's Doc composer and the YouTube
    description both read those keys; both were moved to the minted snapshot
    links in the same wave."""
    writes = re.findall(r'update_link_in_firestore\(\s*([^,]+),', src)
    kinds = {w.strip() for w in writes}
    # ⛔ Two of the four matches are the definition (`kind: str`) and the generic
    # forwarder inside `emit_validated_link` (`link_kind or agent`) — the regex
    # cannot tell a call from a def, so name them rather than loosen the match.
    call_sites = kinds - {"kind: str", "link_kind or agent"}
    assert 'name.lower()' not in call_sites
    # The two direct writes that remain are the brief and the playable audio.
    assert call_sites == {'"brief"', '"audio_file"'}, sorted(call_sites)


# ── 6. the module still holds together ──────────────────────────────────────

def test_research_py_has_no_unresolved_names_left_by_the_cut(src):
    """A cheap whole-module check: every name the removal touched is either gone
    or defined. Catches the shape where a helper survives its only caller."""
    tree = ast.parse(inspect.getsource(research))
    defined = {
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    } | {
        t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name)
    }
    for name in REMOVED:
        assert name not in defined, f"{name} is still defined"
