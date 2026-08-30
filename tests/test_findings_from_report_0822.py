"""Wave 3c: findings come from the report too, and a lost tab stops being a startup failure.

⭐⭐ The findings defect, stated as the run that produces it. A Claude report of
80k characters carrying forty markdown citations; the sources toggle sat disabled
at "Gathered 0 sources", so `progress["source_urls"]` was empty, so the snapshot
was empty, so `if _src_urls:` was false, so `_extract_findings` never ran and
`agent_findings` stayed unset. `save_meta` then wrote three bare heading strings
as "findings" into the SAME agent entry whose `sourceUrls` it had just filled
with forty URLs read out of that very report.

Measured on this machine's logs: 13 of 22 finished Claude runs recorded zero
panel sources, so this is the common path, not an edge case.

⭐ And the ordering claim was false the whole time. The docstring has always
promised "first-mention order in the markdown"; the loop walked PANEL order, so
the 12-cap took the first twelve panel rows whether or not the report cited them.
"""

from __future__ import annotations

import importlib
import inspect

research = importlib.import_module("research")

EF = research._extract_findings


def _report(*paras):
    return "# Claude Deep Research\n\n" + "\n\n".join(paras)


# ── the union ─────────────────────────────────────────────────────────────────

class TestReportIsAnInput:
    def test_a_report_full_of_citations_yields_findings_with_no_panel_at_all(self):
        """THE DEFECT. Zero panel sources used to mean zero findings, however
        many sources the report itself cited."""
        md = _report(
            "## Gut microbiome",
            "A 2025 cohort study found a strong association with diet "
            "diversity, reported at https://nature.com/articles/abc123 in "
            "considerable detail.",
            "A replication attempt is described at https://who.int/reports/xyz "
            "and reaches a weaker conclusion overall.",
        )
        out = EF(md, [])
        assert len(out) == 2
        assert {f["url"] for f in out} == {
            "https://nature.com/articles/abc123", "https://who.int/reports/xyz"}
        assert all(len(f["snippet"]) >= 30 for f in out)

    def test_markdown_link_targets_count_as_citations(self):
        """A report that links rather than pastes is the normal shape.

        ⭐ Covered by the ONE bare-URL scan, and that is a measured claim rather
        than a lucky one: the pattern stops at `)`, `]`, `"`, `'` and `>`, so a
        markdown target ends exactly where the link does. A second markdown-link
        scan was written, found nothing this one missed, and was removed — see
        the two cases below where it would have been strictly worse."""
        md = _report(
            "## Findings",
            "The [original paper](https://arxiv.org/abs/2501.00001) sets out "
            "the method in full and is worth reading closely.")
        out = EF(md, [])
        assert [f["url"] for f in out] == ["https://arxiv.org/abs/2501.00001"]

    def test_a_titled_markdown_link_does_not_glue_the_title_into_the_url(self):
        """⛔ WHY THE SECOND SCAN WAS REMOVED. `[t](https://ex.com/a "Title")`
        makes the markdown-link regex yield `https://ex.com/a "Title"` — which
        starts with `https://`, so it passes every filter and reaches the user as
        a URL with a title glued to it."""
        md = _report(
            "## Findings",
            'See [the study](https://nature.com/a "The Big One") for the '
            "underlying data, which is worth reading closely.")
        out = EF(md, [])
        assert [f["url"] for f in out] == ["https://nature.com/a"]

    def test_an_angle_bracketed_markdown_link_is_read_without_the_brackets(self):
        md = _report(
            "## Findings",
            "See [the study](<https://nature.com/b>) for the underlying data, "
            "which is worth reading closely indeed.")
        out = EF(md, [])
        assert [f["url"] for f in out] == ["https://nature.com/b"]

    def test_panel_and_report_are_unioned_not_replaced(self):
        md = _report(
            "## Both",
            "The panel row is cited here at https://panel.example/one and it "
            "matters for the argument that follows.",
            "This one only the report knows about: https://report.example/two "
            "and it is discussed at some length.")
        out = EF(md, ["https://panel.example/one"])
        assert {f["url"] for f in out} == {
            "https://panel.example/one", "https://report.example/two"}

    def test_a_panel_url_the_report_never_mentions_is_still_skipped(self):
        """Unchanged behaviour, and it must stay: a finding is a SNIPPET from
        the report, so a URL with no mention has no snippet to give."""
        md = _report("## X", "Only this one is cited: https://real.example/a "
                             "and here is enough prose to clear the floor.")
        out = EF(md, ["https://never-mentioned.example/z"])
        assert [f["url"] for f in out] == ["https://real.example/a"]

    def test_no_report_means_no_findings_however_many_panel_urls(self):
        assert EF("", ["https://a.example/1"]) == []
        assert EF(None, ["https://a.example/1"]) == []

    def test_a_report_with_no_urls_yields_nothing(self):
        assert EF(_report("## X", "Prose with no citations at all in it."), []) == []


# ── dedupe ────────────────────────────────────────────────────────────────────

class TestDedupe:
    def test_tracking_params_do_not_split_one_page_into_two_findings(self):
        """The panel delivers a cleaned URL and the report cites the same page
        with `?utm_source=chatgpt.com`. Without a normalised key that is two
        findings for one source."""
        md = _report(
            "## X",
            "The study at https://nature.com/a?utm_source=chatgpt.com is the "
            "one everything else here is arguing about.")
        out = EF(md, ["https://nature.com/a"])
        assert len(out) == 1

    def test_a_real_query_parameter_still_separates_two_pages(self):
        """⛔ The normaliser drops only `utm_*`. Dropping the whole query would
        merge genuinely different pages on any site that paginates there."""
        md = _report(
            "## X",
            "See https://example.com/list?page=1 for the first tranche of the "
            "data, which is the part that matters most.",
            "And https://example.com/list?page=2 for the remainder of it, "
            "which contradicts the first in places.")
        assert len(EF(md, [])) == 2

    def test_case_and_www_do_not_split_a_page(self):
        md = _report("## X",
                     "Cited as https://www.Example.com/a in the body text here, "
                     "with enough words to clear the snippet floor.")
        assert len(EF(md, ["https://example.com/a"])) == 1

    def test_a_differently_spelled_report_citation_still_produces_a_finding(self):
        """⛔ THE TRAP A TEST CAUGHT. The snippet is located by a LITERAL string
        search, so merging on a normalised key while keeping only the panel's
        spelling is strictly WORSE than not merging: the report's own form is
        discarded as a duplicate, the surviving form is nowhere in the text, and
        the finding disappears. Two forms are tracked — one to show, one to
        find."""
        md = _report("## X",
                     "Cited as https://www.Example.com/a in the body text here, "
                     "with enough words to clear the snippet floor.")
        out = EF(md, ["https://example.com/a"])
        assert len(out) == 1
        assert out[0]["url"] == "https://example.com/a", "the clean form is shown"
        assert "body text here" in out[0]["snippet"], "the snippet was found"

    def test_the_emitted_url_is_the_first_seen_form_not_the_key(self):
        """The panel's already-cleaned form must win over the report's tracked
        duplicate — and a normalised KEY must never be emitted as the url."""
        md = _report("## X", "Here it is https://nature.com/a?utm_campaign=x "
                             "in a sentence long enough to keep.")
        out = EF(md, ["https://nature.com/a"])
        assert out[0]["url"] == "https://nature.com/a"


# ── platform chrome ───────────────────────────────────────────────────────────

class TestPlatformChrome:
    def test_the_agents_own_pages_are_not_findings(self):
        md = _report("## X",
                     "As discussed at https://chatgpt.com/c/abc in the thread, "
                     "the conclusion holds up under scrutiny here.")
        assert EF(md, []) == []

    def test_platform_subdomains_are_caught_too(self):
        """⚠ SUFFIX-aware, unlike the exact-set membership tests elsewhere. A
        report cites whatever the agent wrote, and that includes their CDNs."""
        for u in ("https://cdn.openai.com/x.png",
                  "https://files.oaiusercontent.com/y",
                  "https://www.claude.ai/chat/z"):
            md = _report("## X", f"Mentioned at {u} in a sentence with enough "
                                 "words in it to clear the snippet floor.")
            assert EF(md, []) == [], u

    def test_a_host_that_merely_ends_with_a_denied_word_is_kept(self):
        """`notopenai.com` is not `openai.com`. A substring filter would eat it —
        this repo discarded 56% of a run's sources that way once."""
        md = _report("## X", "Reported at https://notopenai.com/a in a sentence "
                             "long enough to survive the floor here.")
        assert [f["url"] for f in EF(md, [])] == ["https://notopenai.com/a"]

    def test_non_http_candidates_are_ignored(self):
        md = _report("## X", "See mailto:a@b.example and ftp://x.example/y and "
                             "https://ok.example/z in this long enough line.")
        assert [f["url"] for f in EF(md, ["mailto:a@b.example"])] == \
            ["https://ok.example/z"]


# ── ordering and the cap ──────────────────────────────────────────────────────

class TestOrderingAndCap:
    def test_findings_come_back_in_first_mention_order(self):
        """The docstring always claimed this; the loop walked panel order."""
        md = _report(
            "## X",
            "First mention is https://one.example/a and here is enough text.",
            "Second mention is https://two.example/b with more text again.",
            "Third mention is https://three.example/c and more text again.")
        panel = ["https://three.example/c", "https://two.example/b",
                 "https://one.example/a"]
        assert [f["url"] for f in EF(md, panel)] == [
            "https://one.example/a", "https://two.example/b",
            "https://three.example/c"]

    def test_the_twelve_cap_takes_the_earliest_cited_not_the_first_panel_rows(self):
        """⭐ The behavioural consequence of the ordering fix: with 20 panel rows
        listed in reverse, the cap used to keep the twelve LAST-cited sources."""
        paras = [f"Mention number {i} is at https://s{i:02d}.example/p and "
                 f"there is plenty of surrounding prose for the snippet."
                 for i in range(20)]
        md = _report("## X", *paras)
        panel = [f"https://s{i:02d}.example/p" for i in reversed(range(20))]
        got = [f["url"] for f in EF(md, panel)]
        assert len(got) == 12
        assert got == [f"https://s{i:02d}.example/p" for i in range(12)]

    def test_the_candidate_list_is_capped_before_the_snippet_walk(self):
        """A report can cite hundreds of URLs; the shared ceiling applies here
        the same as everywhere else that builds a source list."""
        src = inspect.getsource(research._extract_findings)
        assert "_SOURCE_LIST_CAP" in src


# ── the shared bare-URL pattern ───────────────────────────────────────────────

def test_one_definition_of_a_bare_url_serves_both_harvests():
    """`save_meta` fills `sourceUrls` from the same report. Two harvests
    disagreeing about what a URL is would put a source in the list and not in
    the findings — which is exactly the split this wave found.

    ⭐ STRENGTHENED 2026-08-30: they used to share a REGEX and each call it
    themselves; now they share the whole harvest, so the masking, the trimming
    and the pattern cannot drift apart either. The old assertion counted
    `_FIND_BARE_URL_RE.findall(` twice and would now fail on a codebase that is
    strictly safer than the one it was written for.
    """
    src = inspect.getsource(research)
    assert src.count("_FIND_BARE_URL_RE = re.compile(") == 1
    assert src.count("def _sweep_source_urls(") == 1
    # Exactly one caller of the raw regex — the shared harvest itself.
    assert src.count("_FIND_BARE_URL_RE.findall(") == 1
    # And both harvests go through it.
    assert src.count("_sweep_source_urls(") >= 3


class TestCodeIsNotACitation:
    """⛔⛔ THE OWNER'S SCREENSHOT, 2026-08-30: an agent card listing ninety-seven
    "sources" whose visible twelve were `127.0.0.1`, `localhost`,
    `backend.example` and a bare backtick. Cause: both harvests swept the WHOLE
    markdown, so a report that shows you `curl http://localhost:8080/api` had that
    stored as a citation."""

    def test_a_url_inside_a_fence_is_not_a_source(self):
        md = _report("## X",
                     "Real prose cites https://source.android.com/docs here.",
                     "```bash\ncurl http://localhost:8080/api\ncurl http://127.0.0.1:3000/x\n```")
        assert research._sweep_source_urls(md) == ["https://source.android.com/docs"]

    def test_nor_one_in_inline_code(self):
        md = _report("## X", "Point it at `https://backend.example/v1` and then "
                             "read https://real.org/a for the rationale.")
        assert research._sweep_source_urls(md) == ["https://real.org/a"]

    def test_a_tilde_fence_counts_too(self):
        md = _report("## X", "~~~\nhttp://127.0.0.1:9/x\n~~~\nSee https://real.org/b.")
        assert research._sweep_source_urls(md) == ["https://real.org/b"]

    def test_masking_preserves_every_offset(self):
        """⛔⛔ MASKED, NOT STRIPPED, AND THAT IS LOAD-BEARING. `_extract_findings`
        locates each snippet with a literal `md.find(url)`, so deleting bytes
        would slide every offset after the first code block and hand the user a
        snippet from the wrong sentence."""
        md = _report("## X", "```\nhttp://127.0.0.1/x\n```", "Then https://real.org/c matters.")
        masked = research._mask_code(md)
        assert len(masked) == len(md)
        assert md.find("https://real.org/c") == masked.find("https://real.org/c")

    def test_a_fence_containing_a_lone_backtick_does_not_mask_prose(self):
        """⛔ FENCES BEFORE INLINE. Running the inline pass first would pair a
        backtick inside the fence with a later one and mask real prose."""
        md = _report("## X", "```\necho ` http://127.0.0.1/x\n```",
                             "Now https://real.org/d is cited in plain prose.")
        assert "https://real.org/d" in research._sweep_source_urls(md)

    def test_the_trailing_full_stop_comes_off_but_a_balanced_bracket_stays(self):
        md = _report("## X", "Cited https://en.wikipedia.org/wiki/Mercury_(planet). "
                             "And (see https://ok.org/a) as well.")
        assert research._sweep_source_urls(md) == [
            "https://en.wikipedia.org/wiki/Mercury_(planet)", "https://ok.org/a"]

    def test_the_regex_no_longer_swallows_a_backtick(self):
        """⛔ The exclusion set omitted it, so an inline-code URL kept one on its
        tail — the chip that rendered as a lone backtick."""
        assert research._FIND_BARE_URL_RE.findall("x `https://a.org/b` y") == ["https://a.org/b"]

    def test_the_writer_does_not_judge_hosts(self):
        """⛔⛔ DELIBERATELY NOT HERE. A URL not written is gone, `sourceUrls` is
        capped at 50 and never revisited, and the backend reaches a running
        machine only through a pinned release — so it could not have repaired the
        runs the owner was looking at anyway. The frontend carries that rule,
        where a mistake is visible and reversible."""
        md = _report("## X", "Prose mentions https://backend.example/v1 outside code.")
        assert research._sweep_source_urls(md) == ["https://backend.example/v1"]


def test_neither_call_site_still_gates_findings_on_the_panel_list():
    """Both sites used to refuse to run when the panel scrape was empty — the
    common case. Source-pinned: nothing in the suite executes either enclosing
    function."""
    from conftest import code_only_deep
    for fn in (research.extract_and_record_agent,
               research.poll_all_agents_round_robin):
        src = code_only_deep(fn)
        if "_extract_findings(" not in src:
            continue
        for blk in src.split("_extract_findings(")[:-1]:
            tail = blk[-400:]
            assert "if _src_urls:" not in tail, (
                f"{fn.__name__} still refuses to extract findings when the "
                f"panel list is empty"
            )
