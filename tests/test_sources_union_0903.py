"""#278 — the panel's captures were discarded for being second best to nothing.

⛔⛔ THE RULE HAD ITS REASONING RIGHT AND ITS FAILURE CASE MISSING. `save_meta`
wrote the live panel's captured URLs only for an agent with NO report, on the
stated argument that "an agent WITH a report already has citation-derived
sources from its own text, and those are the better list". That is true whenever
a report cites addresses.

On 2026-09-03 not one of three reports contained a single URL — 258 KB of prose
citing by name — so the report-derived list was empty, the report EXISTED, the
fallback was skipped for that reason, and the panel's genuine research hosts
were thrown away in favour of nothing. `sources=0` for all three agents.

⭐ THE REPORT STAYS PRIMARY. Its citations lead, in the order the report made
them, because they are what the agent actually leaned on. The panel FOLLOWS and
answers a different question — what the model opened and did not cite. Neither
can replace the other, and the union is empty only if both rungs were.

⛔ DEDUPED ON THE NORMALISED KEY. A panel row and the report's own citation of
one page differ by the tracking tag the platform adds on the way out, so a raw
dedupe lists the same source twice and inflates the count the user is shown.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402


class _Runtime:
    """Just enough of the runtime for `save_meta`'s snapshot reads."""

    def __init__(self, snaps):
        self.agent_progress_snapshots = snaps


@pytest.fixture
def run_dir(tmp_path):
    (tmp_path / "documents").mkdir()
    return tmp_path


def _write_report(run_dir, platform, body):
    # ⛔ OVER 100 BYTES OR `save_meta` SKIPS THE FILE ENTIRELY — the size gate is
    # what distinguishes a written report from a touched placeholder, and a
    # fixture under it would exercise the no-report path while looking like the
    # one being tested.
    (run_dir / "documents" / f"{platform}.md").write_text(
        body + "\n" + ("filler line to clear the size gate. " * 8), encoding="utf-8")


def _agents(run_dir, snaps=None, monkeypatch=None):
    monkeypatch.setattr(research, "_runtime", _Runtime(snaps or {}), raising=False)
    research.save_meta(run_dir, "a topic", 2)
    return json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))["agents"]


def test_a_report_that_cites_by_name_still_reports_the_panels_sources(run_dir, monkeypatch):
    """⛔⛔ THE 2026-09-03 RUN, EXACTLY. A whole report, correctly cited, holding
    no address — and a panel that captured ten genuine hosts while it was
    written. The old rule reported zero."""
    _write_report(run_dir, "claude",
                  "Hart et al. 2020 (Frontiers in Veterinary Science) reports the effect. "
                  "Torres de la Riva et al. 2013 PLOS ONE agrees.")
    panel = [f"https://journals{i}.example-research.org/a{i}" for i in range(10)]
    got = _agents(run_dir, {"claude": {"source_urls": panel}}, monkeypatch)["claude"]
    assert got["sources"] == 10
    assert got["sourceUrls"] == panel


def test_the_reports_own_citations_come_first(run_dir, monkeypatch):
    """Primary means FIRST, not merely present. The list is capped, so order is
    what decides which sources survive the cap."""
    _write_report(run_dir, "chatgpt",
                  "As shown in https://cited-in-report.org/paper the effect holds.")
    got = _agents(run_dir, {"chatgpt": {"source_urls": ["https://only-in-panel.org/x"]}},
                  monkeypatch)["chatgpt"]
    assert got["sourceUrls"] == ["https://cited-in-report.org/paper",
                                 "https://only-in-panel.org/x"]


def test_one_page_seen_by_both_rungs_is_one_source(run_dir, monkeypatch):
    """⛔ THE TRACKING TAG IS THE WHOLE REASON THE KEY IS NORMALISED. ChatGPT
    appends `?utm_source=chatgpt.com` on the way out, so the panel's row and the
    report's citation of one page are different strings for the same page. A raw
    dedupe shows it twice and tells the user they have one more source than they
    do."""
    _write_report(run_dir, "chatgpt", "See https://docs.nvidia.com/guide for detail.")
    got = _agents(run_dir,
                  {"chatgpt": {"source_urls": ["https://docs.nvidia.com/guide?utm_source=chatgpt.com"]}},
                  monkeypatch)["chatgpt"]
    assert got["sourceUrls"] == ["https://docs.nvidia.com/guide"]
    assert got["sources"] == 1


def test_the_panel_cannot_smuggle_in_the_agents_own_pages(run_dir, monkeypatch):
    """The union is a second way in, so it needs the same host rule the report
    side got — otherwise #277's fix has a door beside it."""
    _write_report(run_dir, "claude", "See https://nature.com/articles/x for detail.")
    got = _agents(run_dir, {"claude": {"source_urls": [
        "https://support.anthropic.com/en/articles/1",
        "https://claude.ai/chat/abc",
        "https://scholar.google.com/citations?user=x",
    ]}}, monkeypatch)["claude"]
    assert got["sourceUrls"] == ["https://nature.com/articles/x",
                                 "https://scholar.google.com/citations?user=x"]


def test_a_non_string_or_non_http_panel_entry_is_ignored(run_dir, monkeypatch):
    """The snapshot is written by page JS and is not trusted to be well-formed —
    a `javascript:` entry must never reach a list the app renders into hrefs."""
    _write_report(run_dir, "gemini", "See https://nature.com/a for detail.")
    got = _agents(run_dir, {"gemini": {"source_urls": [
        None, 42, {"url": "x"}, "javascript:alert(1)", "ftp://f.example-research.org/x",
        "https://ok-source.example-research.org/y",
    ]}}, monkeypatch)["gemini"]
    assert got["sourceUrls"] == ["https://nature.com/a",
                                 "https://ok-source.example-research.org/y"]


def test_the_union_is_capped(run_dir, monkeypatch):
    """The cap is shared with the findings path; the union must respect it rather
    than let the second rung push the list past it."""
    _write_report(run_dir, "chatgpt", " ".join(
        f"https://r{i}.example-research.org/p" for i in range(research._SOURCE_LIST_CAP)))
    panel = [f"https://p{i}.example-research.org/q" for i in range(50)]
    got = _agents(run_dir, {"chatgpt": {"source_urls": panel}}, monkeypatch)["chatgpt"]
    assert len(got["sourceUrls"]) == research._SOURCE_LIST_CAP
    # ⛔ AND THE CAP FALLS ON THE PANEL, NOT THE REPORT. Filling it from the
    # supplementary rung while dropping cited sources would invert their roles.
    assert all("r" == u.split("//")[1][0] for u in got["sourceUrls"])


def test_the_address_handed_to_the_user_is_the_one_the_report_wrote(run_dir, monkeypatch):
    """⛔⛔ THE KEY IS FOR COMPARING, NEVER FOR EMITTING, and the same repo already
    learned this once: `_extract_findings` keeps `emit` and `lookup` as separate
    fields for exactly this reason. Normalisation strips a trailing slash —
    `https://ex.org/a/b/` becomes `https://ex.org/a/b` — and a server that serves
    a directory at one and 404s at the other makes that a broken link. The report's
    author chose an address; the dedupe does not get to rewrite it."""
    _write_report(run_dir, "claude",
                  "Detail at https://docs.example-research.org/guide/?ref=chapter3 applies.")
    got = _agents(run_dir, {"claude": {"source_urls": []}}, monkeypatch)["claude"]
    assert got["sourceUrls"] == ["https://docs.example-research.org/guide/?ref=chapter3"]


def test_a_malformed_snapshot_does_not_lose_the_whole_meta_write(run_dir, monkeypatch):
    """⛔ THE PANEL IS A SUPPLEMENT AND MUST FAIL LIKE ONE. The snapshot is written
    by page JS; a malformed value there must cost the panel's contribution and
    nothing else. Losing `meta.json` would take the phase's whole persisted record
    with it — the report, the sections, the timings."""
    _write_report(run_dir, "claude", "See https://nature.com/a for detail.")
    # ⛔ `None` IS NOT THE CASE THAT REACHES THE GUARD — `or []` already turns it
    # into an empty list, so a null snapshot proves nothing about the try/except.
    # A TRUTHY non-iterable passes `or` untouched and is what actually raises.
    for bad in (None, 42, True, "https://not-a-list.example-research.org/x"):
        got = _agents(run_dir, {"claude": {"source_urls": bad}}, monkeypatch)["claude"]
        assert got["sourceUrls"] == ["https://nature.com/a"], bad


def test_no_panel_snapshot_leaves_the_report_alone(run_dir, monkeypatch):
    _write_report(run_dir, "claude", "See https://nature.com/a for detail.")
    got = _agents(run_dir, {}, monkeypatch)["claude"]
    assert got["sourceUrls"] == ["https://nature.com/a"]


def test_both_rungs_empty_is_still_zero(run_dir, monkeypatch):
    """⛔ THE UNION MUST NOT INVENT ONE. An agent that cited nothing and opened
    nothing has no sources, and saying so is the honest answer — that is what
    made the 2026-09-03 zero worth trusting once the cause was found."""
    _write_report(run_dir, "claude", "Hart et al. 2020 reports the effect.")
    got = _agents(run_dir, {"claude": {"source_urls": []}}, monkeypatch)["claude"]
    assert got["sources"] == 0
    assert got["sourceUrls"] == []
