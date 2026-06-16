"""Bridge serve() port-holder probe — distinguishes a real Super Agent bridge
already on the port from a FOREIGN process squatting it (so serve() can report the
right thing instead of a misleading 'already running')."""

import urllib.request

import pytest

from facade import bridge


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # _port_holder_is_bridge retries with time.sleep between attempts; skip the
    # real waits so the negative cases stay fast.
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)


class _FakeResp:
    def __init__(self, body: bytes):
        self._b = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self) -> bytes:
        return self._b


def test_port_holder_is_bridge_true_on_bridge_healthz(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=2: _FakeResp(b'{"ok": true, "version": "1.2.3"}'))
    assert bridge._port_holder_is_bridge("127.0.0.1", 9876) is True


def test_port_holder_is_bridge_false_on_foreign_server(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=2: _FakeResp(b"<html>some dev server</html>"))
    assert bridge._port_holder_is_bridge("127.0.0.1", 9876) is False


def test_port_holder_is_bridge_false_on_missing_marker(monkeypatch):
    # Valid JSON but not the bridge's {ok, version} shape.
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda url, timeout=2: _FakeResp(b'{"status": "ok"}'))
    assert bridge._port_holder_is_bridge("127.0.0.1", 9876) is False


def test_port_holder_is_bridge_false_on_connection_error(monkeypatch):
    def _boom(url, timeout=2):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert bridge._port_holder_is_bridge("127.0.0.1", 9876) is False


# ── _config_from_settings: map the account's pipeline Settings → run config ──
# Mirrors the web app's Settings→config derivation so an agent run honors the
# same defaults. Field defaults must match the app's DEFAULT_SETTINGS.

def test_config_from_settings_defaults_verify_all():
    assert bridge._config_from_settings({}) == {
        "skipPhases": [],
        "agents": {"chatgpt": True, "gemini": True, "claude": True},
        "videoEnabled": True,
        "emailEnabled": True,
        "podcastLength": "long",
        "skipInitVerify": False,
    }


def test_config_from_settings_none_is_defaults():
    assert bridge._config_from_settings(None)["skipInitVerify"] is False


def test_config_from_settings_skip_init_verify():
    assert bridge._config_from_settings({"skipInitVerify": True})["skipInitVerify"] is True


def test_config_from_settings_agent_selection_and_skip_brief():
    cfg = bridge._config_from_settings({"agentGemini": False, "skipBrief": True})
    assert cfg["agents"] == {"chatgpt": True, "gemini": False, "claude": True}
    assert 1 in cfg["skipPhases"]  # brief skipped


def test_config_from_settings_all_agents_off_skips_research_phase():
    cfg = bridge._config_from_settings(
        {"agentChatGPT": False, "agentGemini": False, "agentClaude": False})
    assert 2 in cfg["skipPhases"]


def test_config_from_settings_podcast_off_skips_podcast_and_video():
    cfg = bridge._config_from_settings({"generatePodcast": False})
    assert set(cfg["skipPhases"]) >= {3, 4}
    assert cfg["videoEnabled"] is False


def test_config_from_settings_video_off_keeps_podcast():
    cfg = bridge._config_from_settings({"generatePodcast": True, "videoLink": "off"})
    assert cfg["videoEnabled"] is False
    assert 3 not in cfg["skipPhases"]  # podcast (P3) still runs, only video (P4) off


def test_config_from_settings_email_and_podcast_length():
    cfg = bridge._config_from_settings({"sendEmail": False, "podcastLength": "short"})
    assert cfg["emailEnabled"] is False
    assert cfg["podcastLength"] == "short"
