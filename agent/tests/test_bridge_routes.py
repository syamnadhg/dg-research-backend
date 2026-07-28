"""Bridge account routes (/researches, /devices, /research) with a fake session.

The bridge is the single owner of the session; these routes are what the CLI
and skill call instead of refreshing the token themselves.
"""

import os
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from facade import bridge


class FakeFS:
    last_enqueue = None
    last_upsert = None
    research_doc = None  # what get_research returns (set per podcast test)
    agent_session_doc = None  # what get_agent_session returns
    user_settings = None  # what get_user_settings returns
    agent_upserts: list = []
    agent_deletes: list = []

    def __init__(self, _token_provider):
        pass

    def get_user_settings(self, uid):
        d = FakeFS.user_settings
        return dict(d) if d else None

    def get_agent_session(self, uid, sid):
        d = FakeFS.agent_session_doc
        return dict(d) if d else None

    def upsert_agent_session(self, uid, sid, fields):
        FakeFS.agent_upserts.append({"uid": uid, "sid": sid, "fields": fields})

    def delete_agent_session(self, uid, sid):
        FakeFS.agent_deletes.append({"uid": uid, "sid": sid})

    def list_researches(self, uid):
        return [{"id": "r1", "title": "Alpha", "status": "completed"}]

    def get_research(self, uid, rid):
        d = FakeFS.research_doc
        return dict(d) if d else None

    def list_devices(self, uid):
        return [{"id": "dev1", "name": "PC", "ownerUid": uid}]

    def upsert_research(self, uid, rid, fields):
        FakeFS.last_upsert = {"uid": uid, "rid": rid, "fields": fields}

    def enqueue_start(self, device_id, **kw):
        FakeFS.last_enqueue = {"device_id": device_id, **kw}
        return "Q-1"

    def delete_research(self, uid, rid):
        pass


@pytest.fixture()
def live(monkeypatch):
    FakeFS.research_doc = None
    FakeFS.agent_session_doc = None
    FakeFS.user_settings = None
    FakeFS.agent_upserts = []
    FakeFS.agent_deletes = []
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    monkeypatch.setattr(bridge.prefs, "get_or_create_install_id", lambda: "iid-test")
    # Isolate the device-selection pref from the real ~/.super-agent/prefs.json.
    sel = {"v": None}
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: sel["v"])
    monkeypatch.setattr(bridge.prefs, "set_selected_device", lambda d, uid: sel.__setitem__("v", d))
    monkeypatch.setattr(bridge.prefs, "clear_selected_device", lambda: sel.__setitem__("v", None))
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(
        uid="u1", email="e@x.y", id_token=lambda force=False: "tok", logout=lambda: None,
    ))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}", state
    finally:
        httpd.shutdown()


def test_researches_route(live):
    base, _ = live
    r = requests.get(base + "/researches")
    assert r.status_code == 200
    assert r.json()["researches"][0]["id"] == "r1"


def test_devices_route(live):
    base, _ = live
    r = requests.get(base + "/devices")
    assert r.status_code == 200
    assert r.json()["devices"][0]["id"] == "dev1"


def test_research_enqueue_route(live):
    base, _ = live
    r = requests.post(base + "/research", json={"topic": "Tesla 2025", "deviceId": "dev1",
                                                "config": {"videoEnabled": False}})
    assert r.status_code == 200
    out = r.json()
    assert out["queueId"] == "Q-1" and out["runId"].startswith("agent-")
    # the enqueue carried the owner uid as submittedBy and the topic
    assert FakeFS.last_enqueue["uid"] == "u1"
    assert FakeFS.last_enqueue["topic"] == "Tesla 2025"
    # the research doc rendered as a real chat (platforms, arrays) and queued
    f = FakeFS.last_upsert["fields"]
    assert f["status"] == "queued" and f["viaAgent"] is True
    assert f["platforms"] and f["documents"] == [] and f["audios"] == []
    # #890: NO phase field — the web app strips it (BE-owned); a bridge-stamped
    # phase:0 flipped the FE to "run started" (Stop/Pause) while still queued.
    assert "phase" not in f
    # #890: sharer display name mirrored like the FE (email local-part fallback)
    assert f["submittedByDisplayName"]


def test_research_applies_account_pipeline_settings(live):
    # The bug fix: an agent run must honor the account's saved pipeline Settings.
    # verifyLogins=True (the opt-in verification toggle) → skipInitVerify False.
    base, _ = live
    FakeFS.user_settings = {"pipeline": {
        "verifyLogins": True, "agentGemini": False, "sendEmail": False,
    }}
    r = requests.post(base + "/research", json={"topic": "T", "deviceId": "dev1"})
    assert r.status_code == 200
    cfg = FakeFS.last_enqueue["config_obj"]
    assert cfg["skipInitVerify"] is False           # user opted INTO verification
    assert cfg["agents"] == {"chatgpt": True, "gemini": False, "claude": True}
    assert cfg["emailEnabled"] is False
    # the research doc mirrors it: pipelineConfig + platforms drop the off agent
    f = FakeFS.last_upsert["fields"]
    assert f["pipelineConfig"]["skipInitVerify"] is False
    assert "gemini" not in f["platforms"] and "chatgpt" in f["platforms"]


def test_verification_is_opt_in_by_default(live):
    # 2026-07-02: no settings at all → skipInitVerify True (verification off —
    # proactive verify navigations are the top bot-score signal).
    base, _ = live
    FakeFS.user_settings = {}
    r = requests.post(base + "/research", json={"topic": "T", "deviceId": "dev1"})
    assert r.status_code == 200
    assert FakeFS.last_enqueue["config_obj"]["skipInitVerify"] is True
    # legacy skipInitVerify:false persisted by the old Settings auto-save is
    # IGNORED (field renamed to verifyLogins precisely so it stops applying)
    FakeFS.user_settings = {"pipeline": {"skipInitVerify": False}}
    r = requests.post(base + "/research", json={"topic": "T2", "deviceId": "dev1"})
    assert r.status_code == 200
    assert FakeFS.last_enqueue["config_obj"]["skipInitVerify"] is True


def test_research_chat_flag_overrides_account_settings(live):
    # An explicit chat flag (--no-email → emailEnabled False) wins over the
    # account default (sendEmail on).
    base, _ = live
    FakeFS.user_settings = {"pipeline": {"sendEmail": True}}
    r = requests.post(base + "/research", json={
        "topic": "T", "deviceId": "dev1", "config": {"emailEnabled": False},
    })
    assert r.status_code == 200
    assert FakeFS.last_enqueue["config_obj"]["emailEnabled"] is False


def test_research_settings_read_failure_falls_back_to_defaults(live, monkeypatch):
    # A settings-read blip must NEVER block a run — fall back to pipeline defaults.
    base, _ = live

    def boom(_uid):
        raise RuntimeError("firestore down")

    monkeypatch.setattr(FakeFS, "get_user_settings", boom)
    r = requests.post(base + "/research", json={"topic": "T", "deviceId": "dev1"})
    assert r.status_code == 200
    cfg = FakeFS.last_enqueue["config_obj"]
    # defaults: verification opt-in (skip True since 2026-07-02), agents all on
    assert cfg["skipInitVerify"] is True and cfg["agents"]["chatgpt"] is True


def test_research_requires_topic(live):
    base, _ = live
    # topic is required; deviceId is now RESOLVED (P2), not required on the wire.
    assert requests.post(base + "/research", json={"deviceId": "d"}).status_code == 400
    # topic alone is fine — the sole fake device is auto-selected.
    assert requests.post(base + "/research", json={"topic": "x"}).status_code == 200


_M4A = ("https://firebasestorage.googleapis.com/v0/b/x/o/"
        "audio%2Fu1%2Fr%2Faudio_overview.m4a?alt=media&token=secret-abc")


def test_podcast_route_downloads_and_hides_token(live, monkeypatch, tmp_path):
    base, _ = live
    FakeFS.research_doc = {
        "id": "agent-1", "title": "Tesla 2025 Outlook", "status": "completed",
        "links": {
            "audio": {"url": "https://notebooklm.google.com/notebook/abc", "label": "Audio Overview"},
            "audio_file": {"url": _M4A, "label": "Podcast Audio (Storage)", "phase": 3},
        },
    }
    captured = {}

    def fake_dl(url, dest_dir, rid):
        captured["url"] = url
        cache = tmp_path / f"{rid}-deadbeef.m4a"  # the ugly rid-hashed cache name
        cache.write_bytes(b"x" * 4096)
        return (cache, 4096)

    monkeypatch.setattr(bridge, "_download_podcast_audio", fake_dl)
    r = requests.get(base + "/research/agent-1/podcast")
    assert r.status_code == 200
    out = r.json()
    assert out["ready"] is True and out["sizeBytes"] == 4096
    assert out["title"] == "Tesla 2025 Outlook"
    assert out["filename"] == "Tesla 2025 Outlook.m4a"  # human filename from the title
    assert out["mime"] == "audio/mp4"
    # localPath is served under a TITLE-based basename (what the chat shows), NOT
    # the rid-hashed cache name — inside a per-run subdir so same-titled runs
    # can't collide — and the delivery copy holds the same bytes.
    assert os.path.basename(out["localPath"]) == "Tesla 2025 Outlook.m4a"
    assert os.path.basename(os.path.dirname(out["localPath"])) == "agent-1-deadbeef"
    assert (tmp_path / "agent-1-deadbeef" / "Tesla 2025 Outlook.m4a").read_bytes() == b"x" * 4096
    # it resolved links.audio_file (the media file), NOT links.audio (the NLM page)
    assert "audio_overview.m4a" in captured["url"]
    # the long-lived Storage download token NEVER leaves the host
    assert "token=" not in r.text and "audioUrl" not in out


def _oversized_doc():
    return {
        "id": "agent-big", "title": "Long Show", "status": "completed",
        "links": {"audio_file": {"url": _M4A, "label": "Podcast Audio (Storage)", "phase": 3}},
    }


def test_podcast_over_platform_ceiling_is_shrunk_for_delivery(live, monkeypatch, tmp_path):
    # A file past the platform's upload ceiling is REFUSED at send time and the
    # runtime silently degrades to printing the path as text (live 2026-07-26: an
    # 89 MB overview arrived as a dead path). Anything oversized must be re-encoded
    # before we hand back a path.
    base, _ = live
    FakeFS.research_doc = _oversized_doc()
    big = bridge._DELIVERY_MAX_BYTES + 1

    def fake_dl(url, dest_dir, rid):
        cache = tmp_path / f"{rid}-deadbeef.m4a"
        cache.write_bytes(b"x" * 16)
        return (cache, big)

    def fake_shrink(cache_path, ceiling):
        small = cache_path.with_name(cache_path.stem + bridge._SHRINK_SUFFIX)
        small.write_bytes(b"y" * 32)
        return small

    monkeypatch.setattr(bridge, "_download_podcast_audio", fake_dl)
    monkeypatch.setattr(bridge, "_shrink_for_delivery", fake_shrink)
    out = requests.get(base + "/research/agent-big/podcast").json()
    assert out["ready"] is True and not out.get("tooLarge")
    assert out["sizeBytes"] == 32                    # the SHRUNK size, not the original
    assert out["mime"] == "audio/mpeg"               # re-encoded to mp3
    assert out["localPath"].endswith("Long Show.mp3")  # still title-named for the chat
    assert out["localPath"] != str(tmp_path / "agent-big-deadbeef.m4a")


def test_podcast_that_cannot_be_shrunk_returns_link_not_a_dead_path(live, monkeypatch, tmp_path):
    # No ffmpeg / still too big → NEVER hand back a path the platform will refuse.
    # The permanent link keeps the podcast reachable.
    base, _ = live
    FakeFS.research_doc = _oversized_doc()

    def fake_dl(url, dest_dir, rid):
        cache = tmp_path / f"{rid}-deadbeef.m4a"
        cache.write_bytes(b"x" * 16)
        return (cache, bridge._DELIVERY_MAX_BYTES + 1)

    monkeypatch.setattr(bridge, "_download_podcast_audio", fake_dl)
    monkeypatch.setattr(bridge, "_shrink_for_delivery", lambda p, c: None)
    monkeypatch.setattr(bridge, "_sr_links", lambda doc: {"podcast": "https://superresearch.io/shared/doc/pod1"})
    out = requests.get(base + "/research/agent-big/podcast").json()
    assert out["tooLarge"] is True
    assert "localPath" not in out                    # nothing that could be sent + fail
    assert out["shareUrl"] == "https://superresearch.io/shared/doc/pod1"


def test_podcast_too_large_mints_the_share_when_absent(live, monkeypatch, tmp_path):
    # _sr_links only READS what's on the doc; the podcast share is written by the P5
    # delivery step. A run asked about before P5 (or started from the web app) would
    # otherwise hand back an EMPTY link — i.e. nothing at all.
    base, _ = live
    FakeFS.research_doc = _oversized_doc()

    def fake_dl(url, dest_dir, rid):
        cache = tmp_path / f"{rid}-deadbeef.m4a"
        cache.write_bytes(b"x" * 16)
        return (cache, bridge._DELIVERY_MAX_BYTES + 1)

    monkeypatch.setattr(bridge, "_download_podcast_audio", fake_dl)
    monkeypatch.setattr(bridge, "_shrink_for_delivery", lambda p, c: None)
    monkeypatch.setattr(bridge, "_sr_links", lambda doc: {})          # nothing minted yet
    monkeypatch.setattr(bridge, "_mint_sr",
                        lambda sess, rid, title: {"podcast": "https://superresearch.io/shared/doc/minted"})
    out = requests.get(base + "/research/agent-big/podcast").json()
    assert out["tooLarge"] is True
    assert out["shareUrl"] == "https://superresearch.io/shared/doc/minted"


def test_delivery_ceiling_is_per_channel(live, monkeypatch, tmp_path):
    # The ceiling belongs to the destination platform: a file that is fine on
    # Telegram is refused on WhatsApp. The route must honour ?platform=.
    base, _ = live
    FakeFS.research_doc = _oversized_doc()
    seen = {}

    def fake_dl(url, dest_dir, rid):
        cache = tmp_path / f"{rid}-deadbeef.m4a"
        cache.write_bytes(b"x" * 16)
        return (cache, 20 * 1024 * 1024)          # 20 MB: fits Telegram, not WhatsApp

    monkeypatch.setattr(bridge, "_download_podcast_audio", fake_dl)
    monkeypatch.setattr(bridge, "_shrink_for_delivery",
                        lambda p, c: seen.__setitem__("ceiling", c))
    # Telegram: 20 MB is under its ceiling → delivered untouched, never re-encoded.
    out = requests.get(base + "/research/agent-big/podcast?platform=telegram").json()
    assert "ceiling" not in seen and out["localPath"].endswith("Long Show.m4a")
    # WhatsApp: the SAME file is over its ceiling → shrink attempted with ITS ceiling.
    requests.get(base + "/research/agent-big/podcast?platform=whatsapp")
    assert seen["ceiling"] == bridge._DELIVERY_LIMITS["whatsapp"]


def test_sms_never_attaches_audio(live, monkeypatch, tmp_path):
    # An MMS carrier cannot carry an overview at any bitrate — go straight to the
    # link rather than burning a multi-minute encode that will be refused anyway.
    base, _ = live
    FakeFS.research_doc = _oversized_doc()
    called = {"n": 0}

    def fake_dl(url, dest_dir, rid):
        cache = tmp_path / f"{rid}-deadbeef.m4a"
        cache.write_bytes(b"x" * 16)
        return (cache, 1024)                       # tiny — but still undeliverable
    monkeypatch.setattr(bridge, "_download_podcast_audio", fake_dl)
    monkeypatch.setattr(bridge, "_shrink_for_delivery",
                        lambda p, c: called.__setitem__("n", called["n"] + 1))
    monkeypatch.setattr(bridge, "_sr_links", lambda doc: {"podcast": "https://superresearch.io/s/x"})
    out = requests.get(base + "/research/agent-big/podcast?platform=sms").json()
    assert out["tooLarge"] is True and called["n"] == 0
    assert out["shareUrl"] == "https://superresearch.io/s/x"


def test_shrink_bitrate_scales_to_the_channel_ceiling():
    # A tight ceiling must lower the rate rather than emit a fixed guess that still
    # overshoots; and anything needing less than the speech floor gets the link.
    half_hour, hour = 1800.0, 3600.0
    tele = bridge._shrink_bitrate_kbps(bridge._DELIVERY_LIMITS["telegram"], half_hour)
    whats = bridge._shrink_bitrate_kbps(bridge._DELIVERY_LIMITS["whatsapp"], half_hour)
    assert tele == bridge._SHRINK_MAX_KBPS          # roomy → stay transparent
    assert bridge._SHRINK_MIN_KBPS <= whats < tele  # tight → scale down, not below floor
    # A full hour simply cannot fit WhatsApp's cap above the speech floor — that must
    # yield None (→ permanent link), never a knowingly-too-big or unlistenable encode.
    assert bridge._shrink_bitrate_kbps(bridge._DELIVERY_LIMITS["whatsapp"], hour) is None
    assert bridge._shrink_bitrate_kbps(bridge._DELIVERY_LIMITS["telegram"], None) \
        == bridge._SHRINK_MAX_KBPS                  # no probe → default, size-checked after


def test_podcast_under_ceiling_is_never_re_encoded(live, monkeypatch, tmp_path):
    # The common case must stay untouched: no ffmpeg cost, original bytes delivered.
    base, _ = live
    FakeFS.research_doc = _oversized_doc()
    called = {"n": 0}

    def fake_dl(url, dest_dir, rid):
        cache = tmp_path / f"{rid}-deadbeef.m4a"
        cache.write_bytes(b"x" * 4096)
        return (cache, 4096)

    monkeypatch.setattr(bridge, "_download_podcast_audio", fake_dl)
    monkeypatch.setattr(bridge, "_shrink_for_delivery",
                        lambda p: called.__setitem__("n", called["n"] + 1))
    out = requests.get(base + "/research/agent-big/podcast").json()
    assert called["n"] == 0 and out["mime"] == "audio/mp4"
    assert out["localPath"].endswith("Long Show.m4a")


def test_shrink_for_delivery_without_ffmpeg_is_none(tmp_path, monkeypatch):
    # ffmpeg is optional for the agent — its absence must degrade to the link path,
    # never raise.
    monkeypatch.setattr(bridge, "_ffmpeg_bin", lambda: None)
    src = tmp_path / "a.m4a"
    src.write_bytes(b"x" * 16)
    assert bridge._shrink_for_delivery(src, bridge._DELIVERY_MAX_BYTES) is None


def test_shrink_for_delivery_rejects_a_result_still_over_the_ceiling(tmp_path, monkeypatch):
    # A re-encode that is STILL too big must not be handed back — the platform would
    # refuse it exactly like the original.
    src = tmp_path / "a.m4a"
    src.write_bytes(b"x" * 16)
    monkeypatch.setattr(bridge, "_ffmpeg_bin", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(bridge, "_audio_duration_seconds", lambda p: None)

    def fake_run(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"z" * (bridge._DELIVERY_MAX_BYTES + 1))
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    assert bridge._shrink_for_delivery(src, bridge._DELIVERY_MAX_BYTES) is None
    assert not list(tmp_path.glob("a-*" + bridge._SHRINK_SUFFIX))   # partial cleaned up


@pytest.mark.skipif(bridge._ffmpeg_bin() is None, reason="ffmpeg not installed")
def test_shrink_for_delivery_really_encodes_with_ffmpeg(tmp_path, monkeypatch):
    # Runs the REAL argv. A fully-mocked subprocess can't catch an argv defect, and
    # one bit us: ffmpeg picks its muxer from the output EXTENSION, and the temp is
    # named "*.part" (required by _prune_podcast_dir's in-flight guard), which claims
    # no muxer — so without an explicit "-f mp3" every encode aborted and the shrink
    # silently degraded to link-only.
    ff = bridge._ffmpeg_bin()
    src = tmp_path / "src.m4a"
    subprocess.run([ff, "-y", "-nostdin", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=3", str(src)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=True)
    out = bridge._shrink_for_delivery(src, bridge._DELIVERY_MAX_BYTES)
    assert out is not None and out.exists() and out.stat().st_size > 0
    assert out.suffix == ".mp3" and out.read_bytes()[:2] in (b"ID", b"\xff\xfb", b"\xff\xf3", b"\xff\xfa")
    assert not list(tmp_path.glob("*.part"))       # temp cleaned up on success


def test_podcast_not_ready_409(live):
    base, _ = live
    FakeFS.research_doc = {"id": "agent-2", "status": "ongoing", "links": {}}
    r = requests.get(base + "/research/agent-2/podcast")
    assert r.status_code == 409
    assert "isn't ready" in r.json()["error"]


def test_podcast_terminal_without_audio_409(live):
    base, _ = live
    FakeFS.research_doc = {"id": "agent-3", "status": "completed", "links": {}}
    r = requests.get(base + "/research/agent-3/podcast")
    assert r.status_code == 409
    assert "no podcast audio" in r.json()["error"]


def test_podcast_missing_run_404(live):
    base, _ = live
    FakeFS.research_doc = None
    assert requests.get(base + "/research/agent-zzz/podcast").status_code == 404


def test_podcast_download_failure_502(live, monkeypatch):
    base, _ = live
    FakeFS.research_doc = {"id": "agent-4", "status": "completed",
                           "links": {"audio_file": {"url": _M4A}}}

    def boom(url, dest_dir, rid):
        raise requests.RequestException("network down")

    monkeypatch.setattr(bridge, "_download_podcast_audio", boom)
    r = requests.get(base + "/research/agent-4/podcast")
    assert r.status_code == 502
    assert "couldn't fetch" in r.json()["error"]


def test_account_routes_401_when_not_signed_in(monkeypatch):
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    state = bridge.BridgeState()
    state.set_session(None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        assert requests.get(base + "/researches").status_code == 401
        assert requests.post(base + "/research", json={"topic": "t", "deviceId": "d"}).status_code == 401
    finally:
        httpd.shutdown()


def test_logout_deletes_agent_session_then_clears(live):
    base, state = live
    r = requests.post(base + "/logout")
    assert r.status_code == 200
    # #790: a clean logout REMOVES the agent identity row entirely (vs the
    # revoke path, which leaves a revoked row), and only THEN tears down session.
    assert FakeFS.agent_deletes == [{"uid": "u1", "sid": "iid-test"}]
    assert state.session is None


# ── podcast download helper + pure helpers (no HTTP server) ──────────────────

class _FakeResp:
    """A minimal stand-in for a streaming requests.Response."""
    def __init__(self, chunks, ok=True):
        self._chunks, self._ok = chunks, ok

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if not self._ok:
            raise requests.HTTPError("boom")

    def iter_content(self, _n):
        return iter(self._chunks)


def test_download_podcast_audio_streams_and_caches(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_get(url, stream=True, timeout=30, allow_redirects=False):
        calls["n"] += 1
        return _FakeResp([b"abc", b"defg"])

    monkeypatch.setattr(bridge.requests, "get", fake_get)
    p, size = bridge._download_podcast_audio(_M4A, tmp_path, "agent-1")
    assert p.exists() and size == 7 and p.read_bytes() == b"abcdefg"
    assert p.name.startswith("agent-1-") and p.name.endswith(".m4a")
    assert not list(tmp_path.glob("*.part"))  # temp renamed away
    # an identical URL is a cache hit — no second download
    p2, size2 = bridge._download_podcast_audio(_M4A, tmp_path, "agent-1")
    assert p2 == p and size2 == 7 and calls["n"] == 1


def test_download_podcast_audio_size_cap_cleans_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "_PODCAST_MAX_BYTES", 4)
    monkeypatch.setattr(bridge.requests, "get",
                        lambda url, stream=True, timeout=30, allow_redirects=False: _FakeResp([b"aa", b"bb", b"cc"]))
    with pytest.raises(ValueError):
        bridge._download_podcast_audio(_M4A, tmp_path, "agent-x")
    assert not list(tmp_path.glob("*"))  # neither the final nor the .part survives


def test_download_podcast_audio_rejects_foreign_host(tmp_path, monkeypatch):
    called = {"n": 0}
    monkeypatch.setattr(bridge.requests, "get",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    for bad in ("http://169.254.169.254/latest/meta-data/",   # internal, and not https
                "https://evil.example.com/x.m4a",             # not a Storage host
                "http://firebasestorage.googleapis.com/x.m4a"):  # right host, wrong scheme
        with pytest.raises(ValueError):
            bridge._download_podcast_audio(bad, tmp_path, "agent-x")
    assert called["n"] == 0  # rejected before any network fetch


def test_prune_age_only_keeps_recent_siblings(tmp_path):
    keep = tmp_path / "agent-1-newhash.m4a"
    sibling = tmp_path / "agent-1-oldhash.m4a"  # same run, different url — must SURVIVE
    aged = tmp_path / "agent-2-x.m4a"           # stale by age — must be pruned
    for f in (keep, sibling, aged):
        f.write_bytes(b"x")
    past = time.time() - bridge._PODCAST_MAX_AGE_SECONDS - 10
    os.utime(aged, (past, past))
    bridge._prune_podcast_dir(tmp_path, keep_name=keep.name)
    assert keep.exists() and sibling.exists()  # recent files (incl. same-run) survive
    assert not aged.exists()                    # only the aged-out file is pruned


def test_podcast_cache_ttl_is_at_least_a_week(tmp_path):
    # TTL was extended 24h→7d so a podcast re-requested within a week is an instant
    # cache hit (not a needless re-download). A file aged ~2 days — stale under the
    # OLD day-long TTL — must now SURVIVE pruning.
    assert bridge._PODCAST_MAX_AGE_SECONDS >= 7 * 24 * 60 * 60
    keep = tmp_path / "agent-1-keep.m4a"
    twodays = tmp_path / "agent-2-2d.m4a"
    for f in (keep, twodays):
        f.write_bytes(b"x")
    past = time.time() - 2 * 24 * 60 * 60  # 2 days old: > old 24h TTL, < new 7d TTL
    os.utime(twodays, (past, past))
    bridge._prune_podcast_dir(tmp_path, keep_name=keep.name)
    assert twodays.exists()  # survives under the week-long TTL


def test_audio_file_url_prefers_media_not_page():
    assert bridge._audio_file_url({"audio_file": {"url": _M4A}}) == _M4A
    assert bridge._audio_file_url({"audio_file": _M4A}) == _M4A  # bare string tolerated
    # only the NotebookLM PAGE kinds present → no media url
    assert bridge._audio_file_url({"audio": {"url": "https://notebooklm.google.com/notebook/x"}}) == ""
    assert bridge._audio_file_url(None) == ""


def test_audio_ext_and_mime():
    assert bridge._audio_ext_and_mime(_M4A) == (".m4a", "audio/mp4")
    assert bridge._audio_ext_and_mime("https://x/y/z.mp3?token=1") == (".mp3", "audio/mpeg")
    assert bridge._audio_ext_and_mime("https://x/y/no-ext?alt=media") == (".m4a", "audio/mp4")


def test_mask_email_hides_full_address_keeps_uid():
    # #11: logs mask the account email (keep first char + domain), but a bare uid
    # (no @) isn't PII and passes through so the log line still identifies the account.
    # RFC 2606 reserved domain — the assertion only needs a multi-char local part,
    # and a realistic-looking personal address is what a future PII grep stops on.
    assert bridge._mask_email("someone@example.com") == "s***@example.com"
    assert bridge._mask_email("firebase-uid-xyz") == "firebase-uid-xyz"
    assert bridge._mask_email("@nolocal.com") == "***@nolocal.com"
    assert bridge._mask_email("") == ""


def test_safe_filename():
    assert bridge._safe_filename("Tesla 2025: Outlook", ".m4a") == "Tesla 2025 Outlook.m4a"  # ':' stripped
    assert bridge._safe_filename("a/b\\c:d?", ".m4a") == "abcd.m4a"  # reserved chars stripped
    assert bridge._safe_filename("日本語のタイトル", ".m4a") == "日本語のタイトル.m4a"  # unicode preserved
    assert bridge._safe_filename("", ".m4a") == "Podcast.m4a"
    assert bridge._safe_filename("   ", ".mp3") == "Podcast.mp3"


def test_podcast_delivery_copy_names_by_title(tmp_path):
    # Delivery copy carries a human, title-based basename inside a per-run subdir
    # (keyed by the unique cache stem); the rid-hashed cache file is left in place
    # (dedup + instant re-ask), and the bytes match.
    cache = tmp_path / "agent-7-abc1234567.mp3"
    cache.write_bytes(b"audio-bytes")
    out = bridge._podcast_delivery_copy(cache, "Mars: Water?", ".mp3")
    assert out.name == "Mars Water.mp3"                 # reserved chars stripped, no rid-hash
    assert out.parent.name == "agent-7-abc1234567"      # per-run subdir → no same-title collision
    assert out.read_bytes() == b"audio-bytes"
    assert cache.exists()                                # cache untouched


def test_podcast_delivery_copy_same_title_different_runs_dont_collide(tmp_path):
    # Two DIFFERENT runs with an IDENTICAL title must resolve to DIFFERENT paths
    # (the same-title race the reviewer caught) — the per-run subdir guarantees it.
    a = tmp_path / "agent-1-aaaaaaaaaa.mp3"; a.write_bytes(b"AAAA")
    b = tmp_path / "agent-2-bbbbbbbbbb.mp3"; b.write_bytes(b"BBBB")
    pa = bridge._podcast_delivery_copy(a, "Same Title", ".mp3")
    pb = bridge._podcast_delivery_copy(b, "Same Title", ".mp3")
    assert pa != pb
    assert pa.name == pb.name == "Same Title.mp3"        # same clean chat name…
    assert pa.read_bytes() == b"AAAA" and pb.read_bytes() == b"BBBB"  # …different bytes, no clobber


def test_podcast_delivery_copy_falls_back_on_error(tmp_path):
    # A missing copy SOURCE must never break the podcast — fall back to the cache
    # path itself (still a valid, servable file in the real flow) and never raise.
    missing = tmp_path / "agent-9-xxxxxxxxxx.mp3"  # deliberately not written
    assert bridge._podcast_delivery_copy(missing, "Whatever", ".mp3") == missing


def test_prune_removes_aged_delivery_subdir_keeps_recent(tmp_path):
    # The title-named delivery SUBDIR is age-pruned like a file: an aged one is
    # rmtree'd, a recent one survives (bounds disk once the flat cache ages out).
    aged = tmp_path / "agent-1-oldhash"; aged.mkdir()
    (aged / "Old Run.m4a").write_bytes(b"x")
    recent = tmp_path / "agent-2-newhash"; recent.mkdir()
    (recent / "New Run.m4a").write_bytes(b"x")
    keep = tmp_path / "agent-3-keep.m4a"; keep.write_bytes(b"x")
    past = time.time() - bridge._PODCAST_MAX_AGE_SECONDS - 10
    os.utime(aged, (past, past))
    bridge._prune_podcast_dir(tmp_path, keep_name=keep.name)
    assert not aged.exists()      # aged subdir gone
    assert recent.exists()        # recent subdir survives
    assert keep.exists()          # cache file untouched
