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
    """Record calls to _update_firestore_research so tests can assert
    the needsFeTrigger marker is written. Without this monkeypatch the
    helper is silent in tests (returns early when _firebase_db /
    _fb_uid / _fb_research_id are unset)."""
    marker_writes = []
    def _fake(payload):
        marker_writes.append(payload)
    monkeypatch.setattr("research._update_firestore_research", _fake)
    return marker_writes


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

    def test_happy_path_writes_marker(self, capture_marker, silent_log):
        """With both ids present, the marker is written and the
        function returns False (no successful Cloud Tasks enqueue
        happens — the FE catch-up hook is the trigger)."""
        from research import _fire_fe_p4_trigger
        result = _fire_fe_p4_trigger("uid-abc", "rid-abc")
        assert result is False
        assert len(capture_marker) == 1
        marker = capture_marker[0]
        assert marker["needsFeTrigger"] is True
        assert isinstance(marker["needsFeTriggerAt"], int)

    def test_marker_write_failure_swallowed(self, monkeypatch, silent_log):
        """If the marker write raises (network blip, permission flap),
        the function logs and returns False — the pipeline doesn't
        crash; the FE catch-up hook will re-fire on next chat-open."""
        def _boom(payload):
            raise RuntimeError("transient firestore error")
        monkeypatch.setattr("research._update_firestore_research", _boom)
        from research import _fire_fe_p4_trigger
        result = _fire_fe_p4_trigger("uid-abc", "rid-abc")
        assert result is False
