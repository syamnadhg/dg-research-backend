"""The 2026-08-06 title tripwire: corroborate before you accuse.

    [13:12:10] [ERROR] [title-refresh] REFUSING the generated title 'NVIDIA Agent
    Stack Architecture And Security Boundaries' — it shares none of the topic's
    distinctive terms (nemoclaw, nemohermes, nemotron, openshell).

Everything about that refusal was right except the alert it raised. NVIDIA is the
vendor of Nemotron; the sources were docs.nvidia.com and build.nvidia.com; the
corpus had already been through `apply_off_topic_sweep` and passed — the run's log
contains no "OFF-TOPIC text REJECTED" line anywhere. So the loud path fired on a
five-word string, the one artefact too short to be evidence, while the artefact
that IS evidence had already voted "on topic".

And the card was worse than the false positive. It arrived after
`phase_complete:2`, so the web app painted it under a header reading "✓ Complete",
and — because the backend passed no `actions` — the app invented a [Skip] button
for a phase that had already finished. The heal had already worked: the title was
refused, the topic-derived name kept, and the notebook renamed to it at 13:13.

⭐ THE RULE, which this project has now paid for twice: alert only when a HUMAN
ACTION is needed. A self-heal is silent. The loud path survives for the shape it
was actually built for — the run whose notebook came out titled "Golden Retriever
Health, Breeding, and Ownership Evidence" — where the CORPUS fails too.
"""

import ast
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import research  # noqa: E402

TOPIC = ("NemoClaw vs NemoHermes vs Nemotron and also about OpenShell and how "
         "all of these can be used for security")

# Verbatim from the run.
INNOCENT_TITLE = "NVIDIA Agent Stack Architecture And Security Boundaries"
# Verbatim from the incident this guard was built for.
DRIFTED_TITLE = "Golden Retriever Health, Breeding, and Ownership Evidence"

ON_TOPIC_CORPUS = ("Nemotron guardrails and NemoClaw deployment notes. " * 800)
OFF_TOPIC_CORPUS = ("Golden retriever coat care and hip dysplasia screening. " * 800)


def test_the_corpora_are_long_enough_for_the_guard_to_judge():
    # `text_is_off_topic` abstains below 20_000 chars. A fixture under that
    # floor would make every case "refuse_silent" and the test would pass
    # without ever exercising the corroboration.
    assert len(ON_TOPIC_CORPUS) > research._TOPIC_GUARD_MIN_CHARS
    assert len(OFF_TOPIC_CORPUS) > research._TOPIC_GUARD_MIN_CHARS
    assert len(research.topic_anchors(TOPIC)) >= research._TOPIC_GUARD_MIN_ANCHORS


class TestTheVerdict:

    def test_a_title_carrying_a_topic_word_is_accepted(self):
        assert research.title_refusal_verdict(
            "NemoClaw vs Nemotron Security Comparison", TOPIC,
            OFF_TOPIC_CORPUS) == "accept"

    def test_the_owners_case_is_refused_silently(self):
        # The whole finding, in one assertion.
        assert research.title_refusal_verdict(
            INNOCENT_TITLE, TOPIC, ON_TOPIC_CORPUS) == "refuse_silent"

    def test_the_incident_case_is_still_loud(self):
        assert research.title_refusal_verdict(
            DRIFTED_TITLE, TOPIC, OFF_TOPIC_CORPUS) == "refuse_loud"

    def test_an_unguardable_topic_still_abstains(self):
        assert research.title_refusal_verdict(
            "Anything At All", "best practices for team retrospectives",
            OFF_TOPIC_CORPUS) == "accept"

    def test_an_empty_title_is_not_an_accusation(self):
        assert research.title_refusal_verdict("", TOPIC, OFF_TOPIC_CORPUS) == "accept"

    def test_a_corpus_too_short_to_judge_stays_silent(self):
        # Uncertain must never be loud — the standing asymmetry everywhere else
        # in this guard.
        assert research.title_refusal_verdict(
            DRIFTED_TITLE, TOPIC, "golden retrievers") == "refuse_silent"

    def test_a_missing_corpus_stays_silent(self):
        assert research.title_refusal_verdict(
            DRIFTED_TITLE, TOPIC, "") == "refuse_silent"

    def test_matching_is_case_insensitive_and_substring(self):
        # "Nemotron-4" and "NemoClaw's" must both count, same as the corpus guard.
        assert research.title_refusal_verdict(
            "NEMOTRON-4 Safety Review", TOPIC, OFF_TOPIC_CORPUS) == "accept"


class TestBothRefusalsStillHeal:
    """The refusal itself was never in doubt and must not have moved."""

    def test_neither_refusal_writes_a_title(self):
        src = inspect.getsource(research._refresh_research_title_async)
        i = src.index("title_refusal_verdict(")
        branch = src[i:src.index('_update_firestore_research({"title"')]
        # One assignment, outside both arms, so a future edit cannot heal on one
        # path and not the other.
        assert branch.count('text = ""') == 1, branch


class TestTheAlertOnlyFiresOnTheLoudVerdict:

    def _emits(self, verdict, monkeypatch):
        """Run the worker body's decision and record what it emitted."""
        recorded = []
        monkeypatch.setattr(research, "emit_event",
                            lambda *a, **k: recorded.append((a, k)))
        logged = []
        monkeypatch.setattr(research, "log",
                            lambda m, lvl="INFO", *a, **k: logged.append((lvl, m)))
        monkeypatch.setattr(research, "title_refusal_verdict",
                            lambda *a, **k: verdict)
        monkeypatch.setattr(research, "_try_llm_title",
                            lambda *a, **k: INNOCENT_TITLE)
        monkeypatch.setattr(research, "_shape_title", lambda t: t)
        monkeypatch.setattr(research, "_firebase_db", None)
        writes = []
        monkeypatch.setattr(research, "_update_firestore_research",
                            lambda d: writes.append(d))
        started = []
        monkeypatch.setattr(research._threading, "Thread",
                            lambda target, **kw: type("T", (), {
                                "start": lambda _s: started.append(target()),
                            })())
        research._refresh_research_title_async(TOPIC, "brief", ON_TOPIC_CORPUS)
        return recorded, logged, writes

    def test_the_silent_verdict_emits_nothing(self, monkeypatch):
        recorded, logged, writes = self._emits("refuse_silent", monkeypatch)
        # ⭐ The silence is only meaningful next to the proof of arrival below:
        # an empty recorder proves nothing if the recorder was never wired.
        assert recorded == [], recorded
        assert writes == [], writes
        assert any("no alert raised" in m for _lvl, m in logged), logged

    def test_the_loud_verdict_emits_exactly_one_warning(self, monkeypatch):
        recorded, _logged, writes = self._emits("refuse_loud", monkeypatch)
        assert len(recorded) == 1, recorded
        args, kwargs = recorded[0]
        assert args[0] == "pipeline_warning"
        assert kwargs.get("phase") == 2
        assert writes == []

    def test_the_loud_card_carries_no_buttons(self, monkeypatch):
        # The phase is already Complete when this can fire. An explicit empty
        # list is what stops the web app inventing a Skip.
        recorded, _l, _w = self._emits("refuse_loud", monkeypatch)
        _args, kwargs = recorded[0]
        assert kwargs.get("actions") == []

    def test_the_loud_card_carries_an_alert_id(self, monkeypatch):
        # Without one, the dismissal ledger can never suppress a re-emit.
        recorded, _l, _w = self._emits("refuse_loud", monkeypatch)
        _args, kwargs = recorded[0]
        assert kwargs.get("alert_id")

    def test_the_loud_card_titles_itself(self, monkeypatch):
        # `error=` would have rendered as the literal string "Backend warning".
        recorded, _l, _w = self._emits("refuse_loud", monkeypatch)
        _args, kwargs = recorded[0]
        assert kwargs.get("message")
        assert "error" not in kwargs

    def test_the_accept_verdict_writes_the_title(self, monkeypatch):
        recorded, _logged, writes = self._emits("accept", monkeypatch)
        assert recorded == []
        assert writes and "title" in writes[0]


class TestTheCorroborationSeesTheWholeCorpus:

    def test_the_uncapped_corpus_is_what_the_verdict_receives(self):
        src = inspect.getsource(research._refresh_research_title_async)
        # `_findings` stays capped for the LLM prompt; the guard must not use it.
        assert "_corpus = (findings_text or \"\").strip()" in src
        assert "_findings = _corpus[:5000]" in src
        i = src.index("title_refusal_verdict(")
        assert "_corpus)" in src[i:i + 120], src[i:i + 120]

    def test_a_capped_corpus_would_have_silenced_everything(self):
        # Why the two strings exist. Feeding the 5000-char sample makes
        # `text_is_off_topic` abstain, so even the golden-retriever run goes quiet.
        assert research.title_refusal_verdict(
            DRIFTED_TITLE, TOPIC, OFF_TOPIC_CORPUS[:5000]) == "refuse_silent"
        assert research.title_refusal_verdict(
            DRIFTED_TITLE, TOPIC, OFF_TOPIC_CORPUS) == "refuse_loud"


class TestEveryWarningCardIsShaped:
    """The lone outlier is what minted the phantom Skip. One guard, no release
    needed to catch the next one."""

    def _warning_calls(self):
        tree = ast.parse(Path(research.__file__).read_text(encoding="utf-8"))
        out = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "emit_event" and node.args):
                continue
            a0 = node.args[0]
            if isinstance(a0, ast.Constant) and a0.value == "pipeline_warning":
                out.append(node)
        return out

    def test_there_are_warnings_to_check(self):
        assert len(self._warning_calls()) >= 10

    def test_every_warning_declares_its_buttons_and_its_identity(self):
        bad = []
        for node in self._warning_calls():
            names = {kw.arg for kw in node.keywords}
            # `None` is the AST's name for a `**base` unpack — those sites share
            # one dict, asserted separately below.
            if None in names:
                continue
            if "actions" not in names or "alert_id" not in names:
                bad.append(node.lineno)
        assert bad == [], (
            f"pipeline_warning at line(s) {bad} omits actions= or alert_id=. "
            f"Omitting actions makes the web app invent a [Skip]; omitting "
            f"alert_id makes the card impossible to dismiss for good."
        )

    def test_the_shared_recovery_payload_declares_them_too(self):
        # The two sites that unpack `**base` — the guard above skips them, so
        # this closes the hole rather than leaving it.
        src = inspect.getsource(research.emit_browser_recovery_status)
        i = src.index("base = {")
        block = src[i:src.index("}", i)]
        assert '"actions": []' in block, block
        assert '"alert_id"' in block, block
