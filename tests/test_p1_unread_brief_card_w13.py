"""A brief that is on ChatGPT's page but could not be read gets its own card (wave 13).

⛔⛔ THE DEFECT. When both reads of Phase 1's brief (the page, then ChatGPT's
Copy button) came back empty, the card always said "No brief was generated —
ChatGPT didn't produce a brief. Make sure ChatGPT is signed in, then Retry" —
also when the brief was plainly on the page. The person was sent to check a
sign-in that was fine, and Retry asked ChatGPT for a whole new brief.

⭐ NOW, when ChatGPT's reply is visibly there (longer than the page read's own
floor), `run_phase1` hands back a way to read it again, the card says the brief
was written but could not be read, and Retry reads it again — it does not ask
ChatGPT for a new one.

▶ EXECUTED, NOT READ. The REAL `run_pipeline` from a resume directory into
Phase 1. `run_phase1` is a stand-in whose result carries the re-read, exactly as
the real one's does (that half is executed on the page in
test_chatgpt_long_brief_w13.py). The run is stopped right after the brief is
taken. Only the edges are stubbed: the network, the log and the browser.
"""
import asyncio

import pytest

import research

BRIEF = "# Research brief: grid storage\n\n" + "Scope and questions for the research. " * 80


class _Accepted(Exception):
    """Raised once the pipeline has taken a brief: the rest is not under test."""


class _FakeBrowser:
    def __init__(self, *_a, **_k):
        self.context = None
        self.page = None

    async def start(self):
        return None

    async def close(self):
        return None

    async def current_url(self):
        return ""


@pytest.fixture
def phase1(tmp_path, monkeypatch):
    queue_dir = tmp_path / "Grid_storage_20260930_101500"
    (queue_dir / "documents").mkdir(parents=True)
    (queue_dir / "config.json").write_text('{"skipInitVerify": true}', encoding="utf-8")
    seen = {"cards": [], "p1_runs": 0, "rereads": 0, "decisions": [], "accepted": 0}

    monkeypatch.setattr(research, "resolve_api_key", lambda *_a, **_k: "test-key")
    monkeypatch.setattr(research, "_capture_anthropic_attribution", lambda *a, **k: None)
    monkeypatch.setattr(research, "clear_clipboard", lambda *a, **k: None)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    monkeypatch.setattr(research, "init_tracks", lambda *a, **k: None)
    monkeypatch.setattr(research, "_cli_mode", False, raising=False)
    monkeypatch.setattr(research, "_login_interrupt_active", lambda: False)
    monkeypatch.setattr(research, "Browser", _FakeBrowser)
    monkeypatch.setattr(research, "_profile_dir", lambda *_a, **_k: tmp_path / "profile")
    monkeypatch.setattr(research, "_update_firestore_research", lambda *a, **k: None)
    monkeypatch.setattr(research, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(research, "detect_resume_phase", lambda _qd: (1, "test: Phase 1"))
    monkeypatch.setattr(research, "_plan_pipeline_auto_retry",
                        lambda *a, **k: (False, 0, False))
    for name in ("_probe_google_credentials", "_post_fe_p4p5_trigger",
                 "_save_meta_in_background", "_observe_dom_success"):
        monkeypatch.setattr(research, name, lambda *a, **k: None)

    async def _none(*_a, **_k):
        return None
    for name in ("run_input_dispatcher", "_probe_cua_available"):
        monkeypatch.setattr(research, name, _none)

    async def _scrub(*_a, **_k):
        return {}
    monkeypatch.setattr(research, "_scrub_persisted_google_auth", _scrub)

    async def _gate(*_a, **_k):
        return "ok"
    monkeypatch.setattr(research, "_phase_verify_gate", _gate)

    def _card(*a, **k):
        seen["cards"].append({"error": k.get("error", a[1] if len(a) > 1 else None),
                              "reason": k.get("reason", a[2] if len(a) > 2 else "")})
    monkeypatch.setattr(research, "fail_phase", _card)

    def _taken(*_a, **_k):
        seen["accepted"] += 1
        raise _Accepted()
    monkeypatch.setattr(research, "_finalize_p2_source_decision", _taken)

    def run(first, rereads, decisions=("retry",)):
        """`first`: what run_phase1 returns (its "reread" filled in here when
        True); `rereads`: what each re-read returns, in order."""
        answers = list(decisions)
        again = list(rereads)

        async def _reread():
            seen["rereads"] += 1
            out = dict(again.pop(0))
            if out.pop("reread", False):
                out["reread"] = _reread
            return out

        async def _run_phase1(*_a, **_k):
            seen["p1_runs"] += 1
            out = dict(first)
            if out.pop("reread", False):
                out["reread"] = _reread
            return out

        # ⛔ Past the planned answers, Stop — never Skip, whose typed-brief wait
        # would sit for three hours on the code before this fix.
        async def _decide(_phase, *a, **k):
            d = answers.pop(0) if answers else "stop"
            seen["decisions"].append(d)
            return d

        monkeypatch.setattr(research, "run_phase1", _run_phase1)
        monkeypatch.setattr(research._controls, "await_phase_decision", _decide)
        monkeypatch.setattr(research._controls, "consume_phase_skip", lambda *a, **k: False)
        asyncio.run(research.run_pipeline(
            topic="Grid storage", resume_dir=str(queue_dir),
            uid=None, email=None, api_key="test-key"))
        return seen

    return run


def test_a_brief_on_the_page_that_could_not_be_read_gets_its_own_card(phase1):
    """⭐⭐ THE FIX. The card says the brief was written and could not be read —
    not "check the sign-in" — and Retry reads it again: run_phase1 is not run a
    second time (no new brief is asked for), and the brief the re-read got is
    the one the run takes."""
    seen = phase1({"text": "", "url": "", "reread": True},
                  rereads=[{"text": BRIEF, "url": ""}])
    assert seen["cards"][0]["error"] == "The brief couldn't be read"
    assert "Retry reads it again" in seen["cards"][0]["reason"]
    assert "signed in" not in seen["cards"][0]["reason"]
    assert not research._web_swallows_title(seen["cards"][0]["error"])
    assert seen["p1_runs"] == 1, "Retry asked ChatGPT for a new brief"
    assert seen["rereads"] == 1
    assert seen["accepted"] == 1, "the re-read brief was not taken"


def test_a_re_read_that_still_cannot_read_it_shows_the_card_again(phase1):
    """The re-read comes back empty with the reply still on the page: the same
    card again, and the next Retry reads once more."""
    seen = phase1({"text": "", "url": "", "reread": True},
                  rereads=[{"text": "", "url": "", "reread": True},
                           {"text": BRIEF, "url": ""}],
                  decisions=("retry", "retry"))
    assert [c["error"] for c in seen["cards"][:2]] == ["The brief couldn't be read"] * 2
    assert seen["p1_runs"] == 1 and seen["rereads"] == 2
    assert seen["accepted"] == 1


def test_no_reply_on_the_page_keeps_the_sign_in_card_and_a_fresh_retry(phase1):
    """A control: with no reply on the page, the old card and the old Retry —
    run_phase1 from the top."""
    seen = phase1({"text": "", "url": ""}, rereads=[], decisions=("retry", "stop"))
    assert seen["cards"][0]["error"] == "No brief was generated"
    assert "signed in" in seen["cards"][0]["reason"]
    assert seen["p1_runs"] == 2 and seen["rereads"] == 0
