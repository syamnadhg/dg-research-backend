"""Cloud Tasks BE→FE handoff tests (research.py:3129 `_fire_fe_p4_trigger`).

Covers Jason's PR-review test-coverage requirement on the autonomous P4
+ P5 trigger introduced in DGOPS-7335. The function has 6 fail-fast
branches (each writes a `needsFeTrigger` marker so the FE catch-up hook
can re-fire on next chat-open) + 1 happy path that enqueues a Cloud Task.

Branches under test:
  1. uid empty / research_id empty (no marker — function can't identify doc)
  2. _DG_FE_BASE_URL unset (write marker)
  3. _DG_FE_CLOUD_TASKS_QUEUE unset (write marker)
  4. _mint_fe_id_token returns None (write marker)
  5. firebase-service-account.json missing (write marker)
  6. client.create_task raises (write marker)
  7. Happy path: task payload shape correct, no marker

Run via:
    pytest tests/test_cloud_tasks.py -v

Tests requiring google.cloud.tasks_v2 will skip cleanly if not installed.
"""
import json
import os
import sys
from unittest import mock

import pytest

# Hack: make research.py importable. The script is at the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def capture_marker(monkeypatch):
    """Record calls to _update_firestore_research so tests can assert
    that the needsFeTrigger marker is written on each fail-fast branch.
    Without this monkeypatch, _update_firestore_research is silent
    (returns early when _firebase_db/_fb_uid/_fb_research_id are unset
    during tests) so marker writes would be unobservable."""
    marker_writes = []
    def _fake(payload):
        marker_writes.append(payload)
    monkeypatch.setattr("research._update_firestore_research", _fake)
    return marker_writes


@pytest.fixture
def silent_log(monkeypatch):
    """Silence module-level log() calls."""
    monkeypatch.setattr("research.log", lambda *a, **kw: None)


@pytest.fixture
def configured_env(monkeypatch):
    """Set the env-derived module constants to valid values. Tests for
    the LATER fail-fast branches need the earlier branches' guards to
    pass; this fixture provides that."""
    monkeypatch.setattr("research._DG_FE_BASE_URL", "https://example.com")
    monkeypatch.setattr(
        "research._DG_FE_CLOUD_TASKS_QUEUE",
        "projects/test-project/locations/us-central1/queues/test-queue",
    )
    monkeypatch.setattr("research._mint_fe_id_token", lambda uid: "fake-id-token-abc")


# ─────────────────────────────────────────────────────────────────────
# Fail-fast branches (no cloud-tasks dep needed)
# ─────────────────────────────────────────────────────────────────────

class TestFireFeP4TriggerFailFastBranches:
    """The 6 fail-fast branches each write a needsFeTrigger marker (except
    the empty-uid/rid branch — which has no Firestore context to flag).
    All return False. Failure is graceful; pipeline doesn't crash."""

    def test_empty_uid_returns_false_without_marker(self, capture_marker, silent_log):
        """Empty uid → can't identify which research doc to mark; just
        log + return False."""
        from research import _fire_fe_p4_trigger
        result = _fire_fe_p4_trigger("", "rid-abc")
        assert result is False
        assert len(capture_marker) == 0

    def test_empty_research_id_returns_false_without_marker(self, capture_marker, silent_log):
        from research import _fire_fe_p4_trigger
        result = _fire_fe_p4_trigger("uid-abc", "")
        assert result is False
        assert len(capture_marker) == 0

    def test_unset_base_url_writes_marker(self, monkeypatch, capture_marker, silent_log):
        """If DG_FE_BASE_URL isn't configured, write marker and bail."""
        from research import _fire_fe_p4_trigger
        monkeypatch.setattr("research._DG_FE_BASE_URL", "")
        result = _fire_fe_p4_trigger("uid-abc", "rid-abc")
        assert result is False
        assert len(capture_marker) == 1
        marker = capture_marker[0]
        assert marker["needsFeTrigger"] is True
        assert "needsFeTriggerAt" in marker
        assert isinstance(marker["needsFeTriggerAt"], int)

    def test_unset_queue_writes_marker(self, monkeypatch, capture_marker, silent_log):
        """If DG_FE_CLOUD_TASKS_QUEUE isn't configured, write marker and bail."""
        from research import _fire_fe_p4_trigger
        monkeypatch.setattr("research._DG_FE_BASE_URL", "https://example.com")
        monkeypatch.setattr("research._DG_FE_CLOUD_TASKS_QUEUE", "")
        result = _fire_fe_p4_trigger("uid-abc", "rid-abc")
        assert result is False
        assert len(capture_marker) == 1
        assert capture_marker[0]["needsFeTrigger"] is True

    def test_mint_id_token_failure_writes_marker(self, monkeypatch, capture_marker, silent_log):
        """If _mint_fe_id_token returns None (Identity Toolkit refused),
        write marker and bail before any Cloud Tasks API call."""
        from research import _fire_fe_p4_trigger
        monkeypatch.setattr("research._DG_FE_BASE_URL", "https://example.com")
        monkeypatch.setattr(
            "research._DG_FE_CLOUD_TASKS_QUEUE",
            "projects/p/locations/us-central1/queues/q",
        )
        monkeypatch.setattr("research._mint_fe_id_token", lambda uid: None)
        result = _fire_fe_p4_trigger("uid-abc", "rid-abc")
        assert result is False
        assert len(capture_marker) == 1


# ─────────────────────────────────────────────────────────────────────
# Cloud Tasks API paths (require google-cloud-tasks)
# ─────────────────────────────────────────────────────────────────────

class TestFireFeP4TriggerCloudTasksPaths:
    """The branches that reach the Cloud Tasks import block need
    google-cloud-tasks installed. pytest.importorskip handles missing
    deps cleanly."""

    def test_missing_sa_file_writes_marker(self, configured_env, capture_marker, silent_log):
        """If firebase-service-account.json doesn't exist, write marker
        and bail (can't construct credentials without it)."""
        pytest.importorskip("google.cloud.tasks_v2")
        pytest.importorskip("google.oauth2.service_account")
        from research import _fire_fe_p4_trigger
        with mock.patch("pathlib.Path.exists", return_value=False):
            result = _fire_fe_p4_trigger("uid-abc", "rid-abc")
        assert result is False
        assert len(capture_marker) == 1
        assert capture_marker[0]["needsFeTrigger"] is True

    def test_create_task_failure_writes_marker(self, configured_env, capture_marker, silent_log):
        """If client.create_task raises (queue missing, IAM denial, quota
        exceeded), the try/except catches and writes the marker. Pipeline
        doesn't crash; FE catch-up hook re-fires on next chat-open."""
        pytest.importorskip("google.cloud.tasks_v2")
        pytest.importorskip("google.oauth2.service_account")
        from research import _fire_fe_p4_trigger
        with mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("google.oauth2.service_account.Credentials.from_service_account_file"), \
             mock.patch("google.cloud.tasks_v2.CloudTasksClient") as MockClient:
            MockClient.return_value.create_task.side_effect = Exception("IAM denied")
            result = _fire_fe_p4_trigger("uid-abc", "rid-abc")
        assert result is False
        assert len(capture_marker) == 1
        assert capture_marker[0]["needsFeTrigger"] is True

    def test_task_payload_shape_on_success(self, configured_env, capture_marker, silent_log):
        """Happy path: create_task is called with the right parent + task
        dict shape. Verifies the URL, headers, body, and dispatch deadline.

        The FE route reads research_id only from the task body; the rest
        (audio_url, title, links) comes from Firestore on receipt via Admin
        SDK. So body MUST be exactly {"research_id": rid}."""
        pytest.importorskip("google.cloud.tasks_v2")
        pytest.importorskip("google.oauth2.service_account")
        from research import _fire_fe_p4_trigger

        # Mock the response so .name attribute is a real string (the function
        # does `response.name.rsplit('/', 1)` for logging).
        mock_response = mock.MagicMock()
        mock_response.name = "projects/test-project/locations/us-central1/queues/test-queue/tasks/abc123"

        with mock.patch("pathlib.Path.exists", return_value=True), \
             mock.patch("google.oauth2.service_account.Credentials.from_service_account_file"), \
             mock.patch("google.cloud.tasks_v2.CloudTasksClient") as MockClient:
            MockClient.return_value.create_task.return_value = mock_response
            result = _fire_fe_p4_trigger("uid-abc", "rid-abc")

        assert result is True
        # Happy path: no marker write (the marker is the fallback signal,
        # only fires when Cloud Tasks isn't reachable).
        assert len(capture_marker) == 0

        # Inspect the call args to verify the task dict shape.
        call_args = MockClient.return_value.create_task.call_args
        assert call_args is not None, "create_task was never called"
        parent = call_args.kwargs["parent"]
        task = call_args.kwargs["task"]
        assert parent == "projects/test-project/locations/us-central1/queues/test-queue"

        http = task["http_request"]
        # URL = base + /api/uploadYouTube (the FE route that owns the
        # autonomous P4+P5 chain post-2026-05-10).
        assert http["url"] == "https://example.com/api/uploadYouTube"
        # Authorization header carries the minted Firebase ID token so
        # the route's verifyRequest resolves to the right uid.
        assert http["headers"]["Authorization"] == "Bearer fake-id-token-abc"
        assert http["headers"]["Content-Type"] == "application/json"
        # Body MUST be exactly {"research_id": rid} — route reads
        # everything else from Firestore.
        body = json.loads(http["body"].decode("utf-8"))
        assert body == {"research_id": "rid-abc"}
        # 30-min per-task deadline (overrides Cloud Tasks' default 10-min
        # dispatch deadline). Long enough for slow ffmpeg encodes /
        # YouTube retries / unverified channel pre-flight failures.
        assert task["dispatch_deadline"] == {"seconds": 1800}
