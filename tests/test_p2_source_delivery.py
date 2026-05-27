"""Tests for the 2026-05-27 Phase-2 source-document delivery fix.

Skip-P1 + user-attached docs (.md/.txt/.pdf/.docx): the source files must
reach EVERY P2 agent, not just sit on disk. The FE sends a synthetic brief
("…using the attached source documents…") and uploads the files; the BE used
to attach only that synthetic brief.md to ChatGPT/Claude (a misleading chip)
and paste the same text to Gemini — so none of the three got the real
content. Now:

  - ChatGPT/Claude attach the sources natively (attach_brief_file extra_files).
  - Gemini gets their text pasted under the brief (it silently drops uploads);
    .md/.txt read natively, .pdf/.docx via import-guarded libs.
  - The files are tracked in a durable per-run manifest ALLOWLIST so P2
    delivery + hard-retry never sweep agent-written artifacts (chatgpt.md …),
    and attach is gated to skip-P1 only (P1-ON already absorbed them).

Because most of the wiring lives inside a 30k-line orchestrator + per-agent
setup, it's covered by (a) real unit tests for the importable sync helpers and
(b) source-contract "alarm" tests that fail if the wiring is reverted.

Run:  pytest tests/test_p2_source_delivery.py -v
"""
import builtins
import inspect
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """Redirect the per-run dir (and thus the manifest + documents/) to a temp
    dir by monkeypatching _p2_run_dir — every manifest helper resolves through
    it, so nothing touches the real queues/ tree."""
    (tmp_path / "documents").mkdir()
    monkeypatch.setattr(research, "_p2_run_dir", lambda: tmp_path)
    return tmp_path


# ─────────────────────────────────────────────────────────────────────
# 1. Manifest allowlist (write / finalize / read)
# ─────────────────────────────────────────────────────────────────────
class TestSourceManifest:
    def test_write_creates_unflagged_manifest(self, run_dir):
        research._write_user_sources_manifest(["a.md", "b.pdf"])
        mp = run_dir / ".p2_sources.json"
        assert mp.exists()
        data = json.loads(mp.read_text())
        assert data["files"] == ["a.md", "b.pdf"]
        assert data["attach_to_p2"] is False  # not delivered until finalized

    def test_manifest_lives_outside_documents(self, run_dir):
        # Must NOT land in documents/ or NotebookLM (P3) would ingest it.
        research._write_user_sources_manifest(["a.md"])
        mp = research._p2_sources_manifest_path()
        assert mp.parent == run_dir
        assert "documents" not in str(mp.parent.name)

    def test_read_empty_until_finalized(self, run_dir):
        research._write_user_sources_manifest(["a.md"])
        (run_dir / "documents" / "a.md").write_text("hi")
        assert research._read_p2_source_paths() == []

    def test_finalize_true_enables_read(self, run_dir):
        research._write_user_sources_manifest(["a.md"])
        (run_dir / "documents" / "a.md").write_text("hi")
        research._finalize_p2_source_decision(True)
        assert research._read_p2_source_paths() == [str(run_dir / "documents" / "a.md")]

    def test_finalize_false_keeps_empty(self, run_dir):
        research._write_user_sources_manifest(["a.md"])
        (run_dir / "documents" / "a.md").write_text("hi")
        research._finalize_p2_source_decision(False)
        assert research._read_p2_source_paths() == []

    def test_finalize_idempotent_preserves_first_decision(self, run_dir):
        # P1-ON decides False; a resume-into-P2 re-evaluates as True but the
        # `decided` guard must keep the original "don't re-attach".
        research._write_user_sources_manifest(["a.md"])
        (run_dir / "documents" / "a.md").write_text("hi")
        research._finalize_p2_source_decision(False)
        research._finalize_p2_source_decision(True)
        assert research._read_p2_source_paths() == []

    def test_read_is_allowlist_excludes_agent_artifacts(self, run_dir):
        # An agent output written into documents/ (chatgpt.md) is NOT on the
        # allowlist → never delivered as a "user source".
        research._write_user_sources_manifest(["src.md"])
        (run_dir / "documents" / "src.md").write_text("hi")
        (run_dir / "documents" / "chatgpt.md").write_text("agent output")
        research._finalize_p2_source_decision(True)
        assert research._read_p2_source_paths() == [str(run_dir / "documents" / "src.md")]

    def test_read_excludes_listed_but_missing_file(self, run_dir):
        research._write_user_sources_manifest(["gone.md"])
        research._finalize_p2_source_decision(True)
        assert research._read_p2_source_paths() == []

    def test_read_no_manifest_returns_empty(self, run_dir):
        assert research._read_p2_source_paths() == []

    def test_finalize_no_files_stays_empty(self, run_dir):
        # decided True but zero files → attach_to_p2 must be False
        research._write_user_sources_manifest([])
        research._finalize_p2_source_decision(True)
        assert research._read_p2_source_paths() == []


# ─────────────────────────────────────────────────────────────────────
# 2. Text extraction (md/txt native; pdf/docx import-guarded)
# ─────────────────────────────────────────────────────────────────────
class TestExtractSourceText:
    def test_md_and_txt_native(self, tmp_path):
        md = tmp_path / "a.md"
        md.write_text("# Title\n\nKEY BODY", encoding="utf-8")
        txt = tmp_path / "b.txt"
        txt.write_text("plain text", encoding="utf-8")
        assert "KEY BODY" in research._extract_source_text(str(md))
        assert research._extract_source_text(str(txt)) == "plain text"

    def test_unknown_ext_returns_none(self, tmp_path):
        f = tmp_path / "x.bin"
        f.write_bytes(b"\x00\x01")
        assert research._extract_source_text(str(f)) is None

    def test_pdf_without_lib_returns_none(self, tmp_path, monkeypatch):
        # Force the import-guard to fail (robust even after `pip install`).
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name in ("pypdf", "PyPDF2"):
                raise ImportError("blocked for test")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        f = tmp_path / "x.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        assert research._extract_source_text(str(f)) is None

    def test_docx_without_lib_returns_none(self, tmp_path, monkeypatch):
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "docx":
                raise ImportError("blocked for test")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        f = tmp_path / "x.docx"
        f.write_bytes(b"PK fake")
        assert research._extract_source_text(str(f)) is None


# ─────────────────────────────────────────────────────────────────────
# 3. Brief augmentation for paste-based delivery (Gemini)
# ─────────────────────────────────────────────────────────────────────
class TestAugmentBriefWithSources:
    def test_no_sources_passthrough(self):
        assert research._augment_brief_with_sources("BRIEF", [], "2C") == "BRIEF"
        assert research._augment_brief_with_sources("BRIEF", None, "2C") == "BRIEF"

    def test_inlines_content_under_header(self, tmp_path):
        src = tmp_path / "notes.md"
        src.write_text("KEY INSIGHT 42", encoding="utf-8")
        out = research._augment_brief_with_sources("BRIEF", [str(src)], "2C")
        assert out.startswith("BRIEF")
        assert "KEY INSIGHT 42" in out
        assert "notes.md" in out
        assert "ATTACHED SOURCE DOCUMENTS" in out

    def test_all_unextractable_passthrough(self, tmp_path, monkeypatch):
        # Every source yields None (e.g. pdf with no lib) → brief unchanged.
        monkeypatch.setattr(research, "_extract_source_text", lambda p: None)
        src = tmp_path / "doc.pdf"
        src.write_bytes(b"%PDF")
        assert research._augment_brief_with_sources("BRIEF", [str(src)], "2C") == "BRIEF"

    def test_per_doc_truncation(self, tmp_path):
        big = tmp_path / "big.md"
        big.write_text("x" * (research._P2_SRC_CHARS_PER_DOC + 5000), encoding="utf-8")
        out = research._augment_brief_with_sources("B", [str(big)], "2C")
        assert "[truncated]" in out
        # body content never exceeds the per-doc cap (header carries no "x")
        assert out.count("x") <= research._P2_SRC_CHARS_PER_DOC

    def test_total_budget_drops_excess_docs(self, tmp_path):
        per = research._P2_SRC_CHARS_PER_DOC
        total = research._P2_SRC_CHARS_TOTAL
        n = (total // per) + 2  # guarantee overflow past the total budget
        paths = []
        for i in range(n):
            p = tmp_path / f"d{i}.md"
            p.write_text(chr(97 + i) * per, encoding="utf-8")
            paths.append(str(p))
        out = research._augment_brief_with_sources("B", paths, "2C")
        headers = out.count("--- SOURCE DOCUMENT:")
        assert 0 < headers < n  # at least one source dropped by the total cap


# ─────────────────────────────────────────────────────────────────────
# 4. Source-contract "alarm" tests — fail if the wiring is reverted
# ─────────────────────────────────────────────────────────────────────
class TestWiringContract:
    def test_start_agent_accepts_source_paths(self):
        sig = inspect.signature(research.start_agent_no_gemini_wait)
        assert "source_paths" in sig.parameters

    def test_cg_claude_attach_threads_extra_files(self):
        src = inspect.getsource(research.start_agent_no_gemini_wait)
        assert "extra_files=source_paths" in src

    def test_gemini_still_uses_paste_not_file_attach(self):
        # The Gemini-drops-uploads revert must stay: Gemini forced off attach.
        src = inspect.getsource(research.start_agent_no_gemini_wait)
        assert "and not is_gemini" in src

    def test_paste_paths_use_augmented_brief(self):
        src = inspect.getsource(research.start_agent_no_gemini_wait)
        assert "_augment_brief_with_sources(brief, source_paths" in src
        # the augmented text — not the raw brief — is what gets pasted
        assert "verified_paste_brief(page, brief_to_paste" in src

    def test_run_phase2_reads_and_threads_to_three_agents(self):
        src = inspect.getsource(research.run_phase2)
        assert "_read_p2_source_paths()" in src
        assert src.count("source_paths=source_paths") >= 3  # 2A / 2B / 2C

    def test_restart_agent_reads_and_threads(self):
        src = inspect.getsource(research._restart_phase2_agent)
        assert "_read_p2_source_paths()" in src
        assert src.count("source_paths=source_paths") >= 3

    def test_orchestrator_tracks_p1_ran_live_and_gates(self):
        src = inspect.getsource(research.run_pipeline)
        assert "_p1_ran_live = False" in src   # init above P1 block (resume-safe)
        assert "_p1_ran_live = True" in src    # set only on live ChatGPT brief
        assert "_finalize_p2_source_decision(not _p1_ran_live)" in src  # P2-entry gate
        # Durable stamp at the live-P1 point so a pause-after-P1 → resume-into-P2
        # can't flip a P1-ON run into double-feeding sources.
        assert "_finalize_p2_source_decision(False)" in src

    def test_flow_b_writes_manifest(self):
        src = inspect.getsource(research.run_pipeline)
        assert "_write_user_sources_manifest(" in src

    def test_requirements_pins_extraction_libs(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        req = open(os.path.join(root, "requirements.txt"), encoding="utf-8").read()
        assert "pypdf" in req
        assert "python-docx" in req
