"""Wave 10.9, 2026-09-22 — the machine stops SAVING the combined document, and
keeps building the string.

⛔⛔ WHAT WENT. One `save_document_to_firestore("consolidated", …)`: the three
agent reports concatenated under one H1, mirrored to the `consolidated` doc type.
`documents/consolidated.md` went on 09-18; this was the last copy. The web's P5
Summary used to read `documents/consolidated` as its ONLY source and refuse
without it, which is why the mirror outlived the disk write — that contract is
gone. The Summary is built from the Super Research document and only from it
(owner's decision D-3; `summary-generate.ts` reads `documents/synthesis`, plus
the three agent reports for the contributor roster alone), the cloud route is the
only runner of phases 4 and 5, and `/api/summary` and `/api/superresearch` no
longer exist.

⛔⛔ WHAT MUST NOT GO WITH IT, AND IT IS WHY THIS FILE EXECUTES RATHER THAN READS.
The string is still built, and it is still handed to TWO readers that take TEXT,
never a saved document:
  · `_generate_research_summary_async` — the one-line `summary` FIELD, the
    paragraph the /researches tile animates.
  · `_refresh_research_title_async` — the post-P2 title refresh.
Both need all three reports at once. Removing the write and the build together
stops both of them SILENTLY: the `len(consolidated_parts) > 1` gate goes False,
no exception, no log line, and every assertion about the write alone still
passes. That is this repo's recorded shape for a silent outage, so the pin has to
watch the readers as well as the writes.

⭐⭐ HOW IT IS MEASURED. `run_pipeline` is four thousand lines behind a browser
and a queue, so the writes it used to do inline could only ever be pinned as
SOURCE TEXT (`test_stacked_document_retired_0918.py`). Wave 10.9 moved them into
`_p2_persist_reports`, which is a module-level function, and this file drives THAT
— the real rehost funnel, the real findings backstop, the real numbering pass —
with Firestore, the image rehost and the two async dispatches faked. Every
assertion below is on what the run WROTE and on what the readers RECEIVED.

⭐ ACCEPT-POLARITY IS HALF THE FILE. An absence pin passes against a helper that
does nothing at all, so the three agent documents are asserted PRESENT, with
their numbered content, and both readers are asserted to have been CALLED with
the merged text — in the same run that proves no combined document was saved.
"""
from __future__ import annotations

import asyncio

import pytest

import research as R

TOPIC = "Grid-scale storage economics"
BRIEF = "What did pack prices do, and what did it cost the operators?"

# Cited reports, so the numbering pass has something to do and the agent
# document a run SAVES is visibly not the text the merged corpus carries.
REPORTS = {
    "ChatGPT": ("## Pack prices\n\nPack prices fell by about a fifth, reported "
                "at https://bnef.example.com/packs and not disputed since.\n"),
    "Gemini": ("## Utilisation\n\nUtilisation rose through the second half, per "
               "https://eia.example.gov/utilisation which publishes monthly.\n"),
    "Claude": ("## Operators\n\nTwo operators re-contracted early, filed at "
               "https://ferc.example.gov/filings/2026-441 in March.\n"),
}


class _Runtime:
    """The two rings `_p2_persist_reports` reads off `_runtime`, empty — which is
    the resume/re-finalize case the findings backstop exists for."""

    def __init__(self):
        self.agent_findings = {}
        self.agent_progress_snapshots = {}


class _Run:
    """What one drive of the persistence helper wrote and dispatched."""

    def __init__(self, queue_dir):
        self.queue_dir = queue_dir
        self.saved = []       # (doc_type, content, name)
        self.summary = []     # (topic, brief, findings_text)
        self.title = []       # (topic, brief, findings_text)

    @property
    def doc_types(self):
        return [t for t, _c, _n in self.saved]

    @property
    def on_disk(self):
        return sorted(p.name for p in (self.queue_dir / "documents").iterdir())

    def content(self, doc_type):
        return next(c for t, c, _n in self.saved if t == doc_type)


def _drive(monkeypatch, tmp_path, results, *, brief=BRIEF, summary_raises=False):
    """The REAL `_p2_persist_reports`, with only Firestore, the image rehost and
    the two daemon dispatches faked. The rehost funnel, the findings backstop and
    the numbered-sources pass all run for real."""
    queue_dir = tmp_path / "run"
    (queue_dir / "documents").mkdir(parents=True)
    run = _Run(queue_dir)

    def _save(doc_type, content, name=None):
        run.saved.append((doc_type, content, name))
        return True

    async def _rehost(text, label=None, **kw):
        return text

    def _summary(topic, brief_text="", findings_text=""):
        run.summary.append((topic, brief_text, findings_text))
        if summary_raises:
            raise RuntimeError("no thread for you")

    def _title(topic, brief_text="", findings_text=""):
        run.title.append((topic, brief_text, findings_text))

    monkeypatch.setattr(R, "_runtime", _Runtime(), raising=False)
    monkeypatch.setattr(R, "save_document_to_firestore", _save)
    monkeypatch.setattr(R, "_rehost_document_images", _rehost)
    monkeypatch.setattr(R, "_generate_research_summary_async", _summary)
    monkeypatch.setattr(R, "_refresh_research_title_async", _title)

    asyncio.run(R._p2_persist_reports(results, queue_dir, TOPIC, brief))
    return run


def _fresh(*names):
    return {n: {"text": REPORTS[n], "status": "done"} for n in names}


def _expected_corpus(*names):
    """The merged text, built the way its readers' prompts expect to read it —
    written out here as a STRING, never by calling the code under test."""
    parts = [f"# Consolidated Research Report: {TOPIC}\n"]
    for n in names:
        parts.append(f"\n## {n} Research\n\n{REPORTS[n]}")
    return "\n".join(parts)


# ── the claim ────────────────────────────────────────────────────────────────


def test_a_completed_run_saves_the_three_agent_reports_and_no_combined_document(
        monkeypatch, tmp_path):
    """⛔⛔ THE WHOLE POINT, AND IT WOULD HAVE FAILED YESTERDAY: the doc types a
    finished Phase 2 writes are the three agents, by EQUALITY. Before this change
    the same drive wrote a fourth, `consolidated`.

    Equality on the list, not `"consolidated" not in`, so the stack cannot come
    back under another doc type either — the same reason the disk-write pin is an
    equality (`test_stacked_document_retired_0918.py`)."""
    run = _drive(monkeypatch, tmp_path, _fresh("ChatGPT", "Gemini", "Claude"))
    assert run.doc_types == ["chatgpt", "gemini", "claude"]
    assert run.on_disk == ["chatgpt.md", "claude.md", "gemini.md"]
    # Accept-polarity: the three that remain are real documents, not empty
    # placeholders a do-nothing helper would also produce.
    for key, name in (("chatgpt", "ChatGPT"), ("gemini", "Gemini"), ("claude", "Claude")):
        saved = run.content(key)
        assert saved.startswith(f"# {name} Deep Research")
        # The prose up to the first citation, which the numbering pass rewrites
        # and everything before is untouched by.
        assert REPORTS[name].split("http", 1)[0].strip() in saved
        assert saved == (run.queue_dir / "documents" / f"{key}.md").read_text(encoding="utf-8")


def test_both_readers_still_receive_the_merged_text_they_receive_today(
        monkeypatch, tmp_path):
    """⛔⛔ THE ONE A WRITE-ONLY DELETION WOULD HAVE BROKEN SILENTLY. The merged
    corpus has no saved copy left, so nothing but this says it is still built —
    and it is the input to the /researches one-liner and to the title refresh.

    The expected text is spelled out in `_expected_corpus`, not obtained from the
    code under test, so a build that changed its shape fails here rather than
    agreeing with itself."""
    run = _drive(monkeypatch, tmp_path, _fresh("ChatGPT", "Gemini", "Claude"))
    corpus = _expected_corpus("ChatGPT", "Gemini", "Claude")
    assert run.summary == [(TOPIC, BRIEF, corpus)]
    assert run.title == [(TOPIC, BRIEF, corpus)]


def test_the_merged_text_carries_the_clean_extraction_not_the_numbered_document(
        monkeypatch, tmp_path):
    """⛔ The saved agent document is the NUMBERED copy — the sources pass rewrites
    the citations and appends a bibliography. The corpus must carry `r["text"]`,
    or the summary and the title refresh are handed numbering markers as prose.
    Executed: the two strings are compared, so this holds without naming either
    side's implementation."""
    run = _drive(monkeypatch, tmp_path, _fresh("ChatGPT"))
    saved = run.content("chatgpt")
    _t, _b, corpus = run.summary[0]
    assert REPORTS["ChatGPT"] in corpus
    assert saved != f"# ChatGPT Deep Research\n\n{REPORTS['ChatGPT']}", (
        "the numbering pass did nothing — this test cannot tell the two copies "
        "apart, so it would pass against a corpus built from the wrong one")
    assert saved.split("\n\n", 1)[1] not in corpus


def test_a_run_where_every_agent_failed_saves_nothing_and_dispatches_nothing(
        monkeypatch, tmp_path):
    """⛔ THE GATE, EXECUTED. With no agent text the corpus is an H1 and nothing
    else, and the two readers must not be asked to summarise a title. Loosening
    `> 1` to `>= 1` is the mutant this kills."""
    run = _drive(monkeypatch, tmp_path,
                 {"ChatGPT": {"text": "", "status": "failed"},
                  "Gemini": {"text": "", "status": "failed"}})
    assert run.saved == [] and run.on_disk == []
    assert run.summary == [] and run.title == []


def test_one_survivor_still_reaches_both_readers(monkeypatch, tmp_path):
    """The other side of the gate: one agent IS a result worth summarising, and
    the corpus is that agent alone. Pins the gate at the right threshold from
    below, so tightening `> 1` to `> 2` fails too."""
    run = _drive(monkeypatch, tmp_path, _fresh("Gemini"))
    assert run.doc_types == ["gemini"]
    assert run.summary == [(TOPIC, BRIEF, _expected_corpus("Gemini"))]
    assert run.title == [(TOPIC, BRIEF, _expected_corpus("Gemini"))]


def test_a_kept_agents_copies_stand_and_its_text_is_still_merged(
        monkeypatch, tmp_path):
    """A resume keeps a finished agent's report: its file and its Firestore copy
    are the ones written when it finished, so the finalize pass must not re-wrap
    them — but its TEXT still belongs in the corpus both readers get."""
    results = _fresh("ChatGPT", "Gemini")
    results["Gemini"]["_restored"] = True
    run = _drive(monkeypatch, tmp_path, results)
    assert run.doc_types == ["chatgpt"]
    assert run.on_disk == ["chatgpt.md"]
    assert run.summary == [(TOPIC, BRIEF, _expected_corpus("ChatGPT", "Gemini"))]


def test_a_failed_summary_dispatch_does_not_cost_the_title_refresh(
        monkeypatch, tmp_path):
    """Two independent daemon dispatches, two `try`s. They are the last thing the
    phase does, so an exception out of either would also skip the run's own
    `PHASE 2 COMPLETE` bookkeeping in the caller."""
    run = _drive(monkeypatch, tmp_path, _fresh("ChatGPT", "Claude"),
                 summary_raises=True)
    corpus = _expected_corpus("ChatGPT", "Claude")
    assert run.summary == [(TOPIC, BRIEF, corpus)]
    assert run.title == [(TOPIC, BRIEF, corpus)]


def test_the_brief_reaches_both_readers_as_the_caller_passes_it(
        monkeypatch, tmp_path):
    """`run_pipeline` hands `brief_artifact.text if brief_artifact else ""`; a run
    with no brief must still refresh its summary and title, from the reports
    alone."""
    run = _drive(monkeypatch, tmp_path, _fresh("Claude"), brief="")
    assert run.summary == [(TOPIC, "", _expected_corpus("Claude"))]
    assert run.title == [(TOPIC, "", _expected_corpus("Claude"))]


# ── the caller, so the helper cannot be a decision nothing asks for ──────────


def test_run_pipeline_hands_the_phase_to_the_helper_unconditionally():
    """⛔⛔ A HELPER A TEST DRIVES AND THE PIPELINE DOES NOT ASK FOR IS A TEST OF
    NOTHING — the shape this repo has paid for before.

    Parsed from the tree: the call is a STATEMENT in the very block that logs
    `PHASE 2 COMPLETE` and checkpoints the phase, with nothing between them. So
    it cannot have been left behind a flag, and it cannot have drifted to a
    branch that a stop, a pause or a failed agent skips — whatever reaches the
    phase's own bookkeeping reaches the writes."""
    import ast
    import inspect

    def _logs_phase_2_complete(s):
        # The STATEMENT itself, never `ast.unparse` of an ancestor: every block
        # enclosing this one contains the same text, and a substring test over
        # them matched four bodies instead of the one that owns the line.
        return (isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                and getattr(s.value.func, "id", "") == "log"
                and "PHASE 2 COMPLETE" in ast.unparse(s.value.args[0]))

    def _awaits_the_helper(s):
        return (isinstance(s, ast.Expr) and isinstance(s.value, ast.Await)
                and isinstance(s.value.value, ast.Call)
                and getattr(s.value.value.func, "id", "") == "_p2_persist_reports")

    fn = ast.parse(inspect.getsource(R.run_pipeline)).body[0]
    bodies = [b for n in ast.walk(fn)
              for b in (getattr(n, "body", []), getattr(n, "orelse", []),
                        getattr(n, "finalbody", []))
              if isinstance(b, list) and any(_logs_phase_2_complete(s) for s in b)]
    assert len(bodies) == 1, "the phase-2 finalize block is not where it was"
    body = bodies[0]
    calls = [i for i, s in enumerate(body) if _awaits_the_helper(s)]
    assert len(calls) == 1, (
        "the phase-2 finalize body does not await `_p2_persist_reports` as a "
        "statement of its own — it is missing, or it has moved behind a branch")
    at = calls[0]
    assert _logs_phase_2_complete(body[at + 1])
    assert "save_checkpoint(queue_dir, 2" in ast.unparse(body[at + 3])
    # And it is handed the phase's own results, the queue and the topic.
    call = body[at].value.value
    assert [ast.unparse(a) for a in call.args][:3] == [
        "results", "queue_dir", "topic"]
    assert ast.unparse(call.args[3]) == (
        "brief_artifact.text if brief_artifact else ''")


@pytest.mark.parametrize("name", ["_generate_research_summary_async",
                                  "_refresh_research_title_async",
                                  "save_document_to_firestore"])
def test_the_faked_names_are_the_real_ones(name):
    """⛔ A monkeypatch on a name the module does not have would make every
    assertion above vacuous — the fake would never be called and the lists would
    be empty for the wrong reason. `raising=True` is the default for the three
    that matter, and this says so out loud."""
    assert callable(getattr(R, name))
