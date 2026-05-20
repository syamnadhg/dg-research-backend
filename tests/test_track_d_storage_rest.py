"""Unit tests for Track D storage REST helpers — user-mode audio upload
+ user-attached source download. The Storage rules + the synth-device-
user authorization check are server-side; these tests cover the BE-side
HTTP wiring: URL shape, headers, success / failure / network-error paths,
download-token URL construction.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import requests
import pytest

research = importlib.import_module("research")


def _make_resp(status: int, body=None, text="", iter_chunks=None):
    class FakeResp:
        status_code = status
        def __init__(self):
            self.text = text
        def json(self):
            if body is None:
                raise ValueError("not JSON")
            return body
        def iter_content(self, chunk_size=64 * 1024):
            for c in (iter_chunks or []):
                yield c
    return FakeResp()


# ─── _resolve_storage_bucket ──────────────────────────────────────────


class TestResolveStorageBucket:
    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("FIREBASE_STORAGE_BUCKET", "my-custom-bucket")
        assert research._resolve_storage_bucket() == "my-custom-bucket"

    def test_default_uses_project_id_convention(self, monkeypatch):
        monkeypatch.delenv("FIREBASE_STORAGE_BUCKET", raising=False)
        from auth import v2_flow as _v2
        monkeypatch.setattr(_v2, "PROJECT_ID", "test-project-123")
        assert research._resolve_storage_bucket() == "test-project-123.firebasestorage.app"


# ─── _upload_audio_via_storage_rest ───────────────────────────────────


class TestUploadAudioViaStorageRest:
    def test_success_returns_download_token_url(self, monkeypatch, tmp_path):
        local = tmp_path / "podcast.mp3"
        local.write_bytes(b"id3-fake-audio-bytes")

        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-abc")
        monkeypatch.setenv("FIREBASE_STORAGE_BUCKET", "sr-test.firebasestorage.app")

        captured = {}
        def fake_post(url, **kwargs):
            captured["url"] = url
            captured["headers"] = kwargs.get("headers", {})
            return _make_resp(200, body={"downloadTokens": "abc-123-xyz,older-token"})

        monkeypatch.setattr(requests, "post", fake_post)
        result = research._upload_audio_via_storage_rest(local, "owner-uid", "rid-9")
        assert result is not None
        assert "audio%2Fowner-uid%2Frid-9%2Fpodcast.mp3" in result
        assert "token=abc-123-xyz" in result
        assert captured["url"].startswith("https://firebasestorage.googleapis.com/v0/b/sr-test.firebasestorage.app/o")
        assert captured["headers"]["Authorization"] == "Firebase tok-abc"
        assert captured["headers"]["Content-Type"] == "audio/mpeg"

    def test_no_token_returns_none_without_calling_post(self, monkeypatch, tmp_path):
        local = tmp_path / "podcast.mp3"
        local.write_bytes(b"x")
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
        called = {"post": False}
        def fake_post(*a, **kw):
            called["post"] = True
            return _make_resp(200)
        monkeypatch.setattr(requests, "post", fake_post)
        assert research._upload_audio_via_storage_rest(local, "owner-uid", "rid-9") is None
        assert called["post"] is False

    def test_non_200_returns_none(self, monkeypatch, tmp_path):
        local = tmp_path / "podcast.mp3"
        local.write_bytes(b"x")
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-abc")
        monkeypatch.setenv("FIREBASE_STORAGE_BUCKET", "sr-test.firebasestorage.app")
        monkeypatch.setattr(
            requests, "post",
            lambda url, **kw: _make_resp(403, body={"error": "Forbidden"}, text="Forbidden"),
        )
        assert research._upload_audio_via_storage_rest(local, "owner-uid", "rid-9") is None

    def test_missing_download_token_returns_none(self, monkeypatch, tmp_path):
        local = tmp_path / "podcast.mp3"
        local.write_bytes(b"x")
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-abc")
        monkeypatch.setenv("FIREBASE_STORAGE_BUCKET", "sr-test.firebasestorage.app")
        monkeypatch.setattr(
            requests, "post",
            lambda url, **kw: _make_resp(200, body={"name": "x", "size": "100"}),
        )
        # Empty `downloadTokens` field → can't build a public URL.
        assert research._upload_audio_via_storage_rest(local, "owner-uid", "rid-9") is None

    def test_network_error_returns_none(self, monkeypatch, tmp_path):
        local = tmp_path / "podcast.mp3"
        local.write_bytes(b"x")
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-abc")
        monkeypatch.setenv("FIREBASE_STORAGE_BUCKET", "sr-test.firebasestorage.app")
        def boom(*a, **kw):
            raise requests.ConnectionError("dns fail")
        monkeypatch.setattr(requests, "post", boom)
        assert research._upload_audio_via_storage_rest(local, "owner-uid", "rid-9") is None

    def test_unresolved_bucket_returns_none(self, monkeypatch, tmp_path):
        local = tmp_path / "podcast.mp3"
        local.write_bytes(b"x")
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-abc")
        monkeypatch.setattr(research, "_resolve_storage_bucket", lambda: "")
        called = {"post": False}
        def fake_post(*a, **kw):
            called["post"] = True
            return _make_resp(200)
        monkeypatch.setattr(requests, "post", fake_post)
        assert research._upload_audio_via_storage_rest(local, "owner-uid", "rid-9") is None
        assert called["post"] is False


# ─── _download_user_source_via_storage_rest ───────────────────────────


class TestDownloadUserSourceViaStorageRest:
    def test_success_writes_file(self, monkeypatch, tmp_path):
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-abc")
        monkeypatch.setenv("FIREBASE_STORAGE_BUCKET", "sr-test.firebasestorage.app")
        captured = {}
        def fake_get(url, **kwargs):
            captured["url"] = url
            captured["headers"] = kwargs.get("headers", {})
            return _make_resp(200, iter_chunks=[b"hello ", b"world"])
        monkeypatch.setattr(requests, "get", fake_get)
        dest = tmp_path / "src.txt"
        ok = research._download_user_source_via_storage_rest(
            "users/owner-uid/researches/rid-9/sources/src.txt", dest,
        )
        assert ok is True
        assert dest.read_bytes() == b"hello world"
        assert "users%2Fowner-uid%2Fresearches%2Frid-9%2Fsources%2Fsrc.txt" in captured["url"]
        assert captured["url"].endswith("?alt=media")
        assert captured["headers"]["Authorization"] == "Firebase tok-abc"

    def test_no_token_returns_false_without_calling_get(self, monkeypatch, tmp_path):
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: None)
        called = {"get": False}
        def fake_get(*a, **kw):
            called["get"] = True
            return _make_resp(200)
        monkeypatch.setattr(requests, "get", fake_get)
        ok = research._download_user_source_via_storage_rest(
            "users/x/researches/y/sources/f.txt", tmp_path / "f.txt",
        )
        assert ok is False
        assert called["get"] is False

    def test_404_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-abc")
        monkeypatch.setenv("FIREBASE_STORAGE_BUCKET", "sr-test.firebasestorage.app")
        monkeypatch.setattr(
            requests, "get",
            lambda url, **kw: _make_resp(404, text="Not Found"),
        )
        ok = research._download_user_source_via_storage_rest(
            "users/x/researches/y/sources/missing.txt", tmp_path / "out.txt",
        )
        assert ok is False
        assert not (tmp_path / "out.txt").exists()

    def test_network_error_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-abc")
        monkeypatch.setenv("FIREBASE_STORAGE_BUCKET", "sr-test.firebasestorage.app")
        def boom(*a, **kw):
            raise requests.ConnectionError("dns fail")
        monkeypatch.setattr(requests, "get", boom)
        ok = research._download_user_source_via_storage_rest(
            "users/x/researches/y/sources/f.txt", tmp_path / "f.txt",
        )
        assert ok is False
