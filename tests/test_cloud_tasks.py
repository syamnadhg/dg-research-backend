"""Tests for `_fire_fe_p4_trigger` after the Track D D8 cutover.

Post-cutover the function no longer enqueues a Cloud Task (the BE has
no Admin SDK service account to authenticate to Cloud Tasks). Instead
it writes a `needsFeTrigger: true` marker on the research doc; the FE
catch-up hook picks that up on next chat-open and re-fires the
autonomous P4 + P5 chain via FE-side credentials.

The old "task payload shape" / "Cloud Tasks enqueue" tests are gone
with the legacy code path.
"""

import os
import sys

import pytest

# Make research.py importable. The script is at the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def capture_marker(monkeypatch):
    """Record the marker write so tests can assert what reached the document.

    ⛔ IT USED TO STUB `_update_firestore_research`, which takes its target from
    the pipeline globals and returns None on every path. The write is addressed
    now — `_update_research_doc(uid, rid, payload)` — because this function is
    called for runs the worker is NOT executing (the boot rehydrate, a Resume),
    and because its bool is what the log line has to report (wave 10.9,
    542-S4). Each entry is (uid, rid, payload)."""
    marker_writes = []

    def _fake(uid, rid, payload):
        marker_writes.append((uid, rid, payload))
        return True

    monkeypatch.setattr("research._update_research_doc", _fake)
    return marker_writes


@pytest.fixture
def captured_log(monkeypatch):
    """Every log line, with its level."""
    lines = []
    monkeypatch.setattr("research.log",
                        lambda msg, level="INFO", *a, **k: lines.append((level, str(msg))))
    return lines


@pytest.fixture
def silent_log(monkeypatch):
    monkeypatch.setattr("research.log", lambda *a, **kw: None)


class TestFireFeP4Trigger:
    def test_empty_uid_skips_marker(self, capture_marker, silent_log):
        """Without a uid the function has no Firestore context — log
        + return False without writing the marker."""
        from research import _fire_fe_p4_trigger
        result = _fire_fe_p4_trigger("", "rid-abc")
        assert result is False
        assert len(capture_marker) == 0

    def test_empty_research_id_skips_marker(self, capture_marker, silent_log):
        from research import _fire_fe_p4_trigger
        result = _fire_fe_p4_trigger("uid-abc", "")
        assert result is False
        assert len(capture_marker) == 0

    def test_happy_path_writes_marker_to_the_named_run(self, capture_marker, silent_log):
        """With both ids present the marker is written — to the run this call
        NAMES, not to whatever the pipeline globals happen to hold."""
        from research import _fire_fe_p4_trigger
        result = _fire_fe_p4_trigger("uid-abc", "rid-abc")
        assert result is True
        assert len(capture_marker) == 1
        uid, rid, marker = capture_marker[0]
        assert (uid, rid) == ("uid-abc", "rid-abc")
        assert marker["needsFeTrigger"] is True
        assert isinstance(marker["needsFeTriggerAt"], int)

    def test_marker_write_failure_swallowed(self, monkeypatch, silent_log):
        """If the marker write raises (network blip, permission flap),
        the function logs and returns False — the pipeline doesn't crash, and
        a chat opening on the run re-kicks the route anyway."""
        def _boom(uid, rid, payload):
            raise RuntimeError("transient firestore error")
        monkeypatch.setattr("research._update_research_doc", _boom)
        from research import _fire_fe_p4_trigger
        result = _fire_fe_p4_trigger("uid-abc", "rid-abc")
        assert result is False

    def test_a_marker_that_did_not_land_is_not_reported_as_written(
            self, monkeypatch, captured_log):
        """⛔⛔ THE FIRST OF THE TWO LINES A STUCK-RUN REPORT IS READ FROM
        (wave 10.9, 542-S4). `_update_research_doc` LOGS its own failure and
        returns False — it does not raise — and the old code went straight on
        to print "needsFeTrigger marker written". So the support line said the
        backstop was in place over a document that had never been written, and
        every report resting on it started from a false premise.

        ⛔ A NEGATIVE ALONE WOULD NOT CATCH IT: deleting the success line
        entirely also removes the false sentence. The failure has to be SAID."""
        monkeypatch.setattr("research._update_research_doc",
                            lambda uid, rid, payload: False)
        from research import _fire_fe_p4_trigger
        assert _fire_fe_p4_trigger("uid-abc", "rid-abc") is False
        said = [m for _lvl, m in captured_log]
        assert not any("marker written" in m for m in said), (
            "a marker that never reached the document was reported as written")
        assert any("NOT written" in m for m in said), (
            "the failed marker write said nothing at all — the report it feeds "
            "cannot tell a missing backstop from a working one")
        assert any(lvl == "WARN" for lvl, m in captured_log if "NOT written" in m)

    def test_a_marker_that_landed_says_so(self, capture_marker, captured_log):
        """⭐ ACCEPT POLARITY. The honest failure line must not cost the honest
        success line: a run whose marker IS on the document still says so, and
        at INFO."""
        from research import _fire_fe_p4_trigger
        assert _fire_fe_p4_trigger("uid-abc", "rid-abc") is True
        assert any("marker written" in m and lvl != "WARN"
                   for lvl, m in captured_log)
