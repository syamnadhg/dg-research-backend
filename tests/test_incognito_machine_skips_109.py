"""The machine writes I stopped making for a run that keeps nothing.

⛔⛔ THESE ARE THE WRITES THAT OUTLIVE A RUN, and each one of them is a place the
pipeline reached without asking whose research it was:

  · the podcast — an mp3 in a Storage bucket with no TTL and no purge, an
    `audios` row the Podcasts page lists from, and `links.audio_file`;
  · the report figures — every image in an agent's document, fetched and stored
    in the same bucket;
  · the phase notices — a row in somebody's inbox, pointing at a chat that will
    not exist;
  · the Send Logs picker — a run this person can name and send to support;
  · boot recovery — a Resume card in a chat that cannot be reopened, holding a
    run non-terminal until its fuse burns out, or an auto-resume that re-opens
    somebody's private research hours later on another person's browser.

⭐ EVERY PIN RUNS THE REAL FUNCTION against fakes, and every refusal is paired
with the ordinary `chat_` run it must not touch — the whole risk of this commit
is a gate that fires for everybody.
"""
import asyncio
import base64
import collections
import hashlib
import struct
import types

import pytest
import requests

import research


def _png(w=100, h=60):
    """A PNG header the funnel's own sniff accepts — a run of zero bytes is
    refused, and the accept-polarity pin would then pass for the wrong reason."""
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
            + struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0) + b"\x00\x00\x00\x00")

UID = "uid-sharer"
INCOG = "incog_1758400000000_3"
CHAT = "chat_1758400000000_3"
PRIVATE = "https://chatgpt.com/c/f00d-cafe"
IMAGE = "https://img.example.com/figure.png"


# ══ 1. the report figures ═════════════════════════════════════════════════

@pytest.fixture()
def images(monkeypatch):
    """The image funnel with a fake web behind it — one fetch, one upload."""
    w = types.SimpleNamespace(fetches=[], posts=[], logs=[])
    monkeypatch.setattr(research, "_fb_uid", UID)
    monkeypatch.setattr(research, "_doc_img_cache", collections.OrderedDict())
    monkeypatch.setattr(research, "_doc_img_decorative_pending", 0)
    monkeypatch.setattr(research, "_doc_img_resolve_host",
                        lambda host, port, deadline: ["93.184.216.34"])
    # A fresh Stop/Pause state and no scheduled exit: either one would send an
    # ordinary run down the offline pass and make the accept polarity below
    # pass for the wrong reason.
    monkeypatch.setattr(research, "_controls", research.PipelineControls())
    monkeypatch.setattr(research, "_exit_scheduled", False)
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: "tok-1")

    def fetch(url, deadline):
        w.fetches.append(url)
        return _png()
    monkeypatch.setattr(research, "_doc_img_fetch", fetch)

    def post(url, headers=None, json=None, timeout=None, **kw):
        w.posts.append(url)
        # The reference is only accepted when it names THIS research and THESE
        # bytes, so the fake web has to compute it the way a real one would —
        # otherwise the accept-polarity pin below fails for its own reason.
        data = base64.b64decode(json["data_base64"])
        ref = (f"/document-images/{json['research_id']}/"
               f"{hashlib.sha256(data).hexdigest()}.png")
        return types.SimpleNamespace(status_code=200, text="{}",
                                     json=lambda: {"ref": ref})
    monkeypatch.setattr(requests, "post", post)

    class _Session:
        def post(self, url, **kw):
            return post(url, **kw)

        def close(self):
            pass
    monkeypatch.setattr(research, "_doc_img_upload_session", lambda guard: _Session())
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: w.logs.append(str(msg)))
    return w


def _rehost(monkeypatch, rid, text):
    monkeypatch.setattr(research, "_fb_research_id", rid)
    return asyncio.run(research._rehost_document_images(text, "ChatGPT"))


def test_an_ordinary_runs_figure_is_still_fetched_and_stored(images, monkeypatch):
    """⭐ ACCEPT POLARITY FIRST. The funnel exists because an agent's document
    points at images only that agent can open; turning it off for everybody
    would break every report in the product."""
    out = _rehost(monkeypatch, CHAT, f"![Figure 1]({IMAGE})")
    assert images.fetches == [IMAGE] and images.posts, "the ordinary path stopped storing"
    assert "/document-images/" in out


def test_a_run_that_keeps_nothing_fetches_and_stores_no_figure(images, monkeypatch):
    """⛔⛔ THE BUCKET IS THE ONE RESIDUE WITH NO FUSE. Storage has no TTL, the
    purge does not reach it, and the rules' one lifecycle rule covers `logs/`."""
    out = _rehost(monkeypatch, INCOG, f"![Figure 1]({IMAGE})")
    assert images.fetches == [], f"an incognito run fetched: {images.fetches}"
    assert images.posts == [], f"an incognito run uploaded: {images.posts}"
    assert IMAGE not in out, "the image's own address survived into the document"
    assert "Figure 1" in out, "the caption should keep what the image was of"


def test_the_private_link_scrub_still_runs_on_a_run_that_keeps_nothing(
        images, monkeypatch):
    """⛔⛔ THE SEAM. The scrub is the OTHER half of this funnel and it runs on
    whatever the image half hands back. A skip placed at the funnel instead of
    inside the image half would take the scrub with it — writing the agents'
    signed file links and conversation addresses into the saved text and into
    everything built from it, which for an incognito run is the mail."""
    out = _rehost(monkeypatch, INCOG, f"See [the chat]({PRIVATE}) for the rest.")
    assert PRIVATE not in out, f"a private conversation address survived: {out}"
    assert "the chat" in out, "the link's text should stay, only its destination goes"


def test_the_scrub_still_runs_for_an_ordinary_run_too(images, monkeypatch):
    """⭐ ACCEPT POLARITY on the seam itself."""
    out = _rehost(monkeypatch, CHAT, f"See [the chat]({PRIVATE}) for the rest.")
    assert PRIVATE not in out and "the chat" in out


# ══ 2. the podcast ════════════════════════════════════════════════════════

@pytest.fixture()
def podcast(monkeypatch, tmp_path):
    """Phase 3's three publishing writes, each recorded instead of performed."""
    w = types.SimpleNamespace(uploads=[], audios=[], links=[], logs=[])
    monkeypatch.setattr(research, "upload_audio_to_storage",
                        lambda p: (w.uploads.append(p) or "https://storage/a.m4a"))
    monkeypatch.setattr(research, "save_audio_to_firestore",
                        lambda *a: w.audios.append(a))
    monkeypatch.setattr(research, "update_link_in_firestore",
                        lambda kind, url, **kw: w.links.append((kind, url)))
    monkeypatch.setattr(research, "_audio_duration_sec", lambda p: 631)
    monkeypatch.setattr(research, "log",
                        lambda msg, level="INFO", *a, **k: w.logs.append(str(msg)))
    w.path = tmp_path / "Deep_Dive_conversation.m4a"
    w.path.write_bytes(b"audio")
    return w


def test_an_ordinary_runs_podcast_is_still_published(podcast):
    """⭐ ACCEPT POLARITY. `links.audio_file` is what FE-P4's video gate, the
    shared player and the in-chat Play button all read — a gate that fired for
    everybody would silently stop every podcast in the product."""
    url = asyncio.run(research._p3_publish_audio(podcast.path, CHAT))
    assert url == "https://storage/a.m4a"
    assert podcast.uploads == [podcast.path]
    assert podcast.audios and podcast.audios[0][0] == podcast.path.stem
    assert podcast.links == [("audio_file", "https://storage/a.m4a")]


def test_a_run_that_keeps_nothing_publishes_no_podcast(podcast):
    """⛔⛔ ALL THREE WRITES, and the mp3 is the one with no fuse at all —
    Storage has no TTL and the purge does not reach it."""
    assert asyncio.run(research._p3_publish_audio(podcast.path, INCOG)) == ""
    assert podcast.uploads == [], "an incognito run uploaded its podcast"
    assert podcast.audios == [], "an incognito run wrote an audios row"
    assert podcast.links == [], "an incognito run wrote links.audio_file"


def test_a_run_with_no_audio_file_still_publishes_nothing(podcast):
    """⭐ The pre-existing behaviour, kept: no file, no writes, no raise."""
    assert asyncio.run(research._p3_publish_audio(None, CHAT)) == ""
    assert podcast.uploads == []


def test_a_failed_upload_still_answers_empty_rather_than_a_local_path(podcast,
                                                                     monkeypatch):
    """⛔ THE COMPLETION ARTEFACT. A local file with a failed upload must not
    read as a published podcast — that disagreement between completion and
    delivery is what this return value was added for."""
    monkeypatch.setattr(research, "upload_audio_to_storage", lambda p: None)
    assert asyncio.run(research._p3_publish_audio(podcast.path, CHAT)) == ""
    assert podcast.links == []


# ══ 3. the phase notices ══════════════════════════════════════════════════

@pytest.fixture()
def notices(monkeypatch):
    w = types.SimpleNamespace(posts=[], tokens=0)

    def token():
        w.tokens += 1
        return "tok-1"
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", token)

    class _Inline:
        def __init__(self, target=None, **kw):
            self._t = target

        def start(self):
            self._t()
    monkeypatch.setattr(research._threading, "Thread", _Inline, raising=False)

    def post(url, headers=None, json=None, timeout=None, **kw):
        w.posts.append(json)
        return types.SimpleNamespace(status_code=200, text="ok")
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    return w


def test_an_ordinary_run_still_asks_for_its_phase_notice(notices):
    """⭐ ACCEPT POLARITY. This call is the whole answer to a closed tab —
    without it a phase's notifications wait until somebody comes back."""
    assert research._post_fe_phase_notice(UID, CHAT, 3, "phase_complete", 12) is True
    assert notices.posts and notices.posts[0]["phaseNotice"]["researchId"] == CHAT


def test_a_run_that_keeps_nothing_asks_for_no_notice(notices):
    """⛔ AN INBOX ROW OUTLIVES THE RUN, and its `/research/{id}` link points at
    a chat that will not exist. And the closed tab this call exists for cannot
    be reopened for an incognito chat anyway."""
    assert research._post_fe_phase_notice(UID, INCOG, 3, "phase_complete", 12) is False
    assert notices.posts == [], f"an incognito run asked for a notice: {notices.posts}"
    assert notices.tokens == 0, "it even minted a token for a request it must not send"


# ══ 4. the Send Logs picker ═══════════════════════════════════════════════

def _row(rid, uid=UID, started=100.0):
    return {"researchId": rid, "submitterUid": uid, "startedEpoch": started,
            "name": "f", "status": "complete", "attempt": 0, "sizeBytes": 1,
            "events": 0, "durationSec": 1, "counters": {}, "startedUtc": "",
            "storedStatus": "complete", "worker": 1, "build": "b",
            "parentResearchId": None, "submitterSource": "app", "dir": "d"}


def test_the_picker_still_offers_an_ordinary_run():
    """⭐ ACCEPT POLARITY — the picker's whole point is that the app cannot know
    what is on that disk, so an empty document is a feature nobody can use."""
    out = research._run_index_by_submitter([_row(CHAT)])
    assert [r["researchId"] for r in out[UID]["runs"]] == [CHAT]


def test_the_picker_never_offers_a_run_that_keeps_nothing():
    """⛔ A row here is a run the person can name and send to support — a run
    that appears in no list by design, offered back to them by id."""
    out = research._run_index_by_submitter([_row(INCOG)])
    assert out == {}, f"an incognito run reached the picker: {out}"


def test_a_persons_other_runs_still_reach_the_picker_beside_one_that_keeps_nothing():
    """⛔ DROPPED ROW BY ROW, not by refusing the submitter. A person with one
    incognito run must not lose their ordinary ones from the picker.

    ⭐ THE INCOGNITO ROW COMES FIRST, deliberately: with it last, a scan that
    STOPPED at the first one would still have collected the ordinary run and
    this pin would have passed."""
    out = research._run_index_by_submitter([_row(INCOG, started=300.0),
                                            _row(CHAT, started=200.0)])
    assert [r["researchId"] for r in out[UID]["runs"]] == [CHAT]


# ══ 5. boot recovery ══════════════════════════════════════════════════════

def test_an_ordinary_run_is_still_parked_for_a_resume():
    """⭐ ACCEPT POLARITY. The Resume card is how a run survives a restart."""
    patch = research._restart_recovery_patch(CHAT)
    assert patch["status"] == "paused_backend_restart" and "Resume" in patch["summary"]


def test_a_run_that_keeps_nothing_is_ended_instead():
    """⛔⛔ `paused_backend_restart` IS AN OFFER, and an incognito chat is in no
    list and cannot be reopened — so the card appears nowhere and nobody can
    press it, while the run stays non-terminal, holding its documents and its
    folder, until the fuse burns out."""
    patch = research._restart_recovery_patch(INCOG)
    assert patch["status"] == "stopped"
    assert "Resume" not in patch["summary"]


def test_the_stop_sentence_promises_nothing_about_what_is_kept():
    """⛔ WAVE 6'S RULE. What is kept, and for how long, is said by the app in
    the commit that makes it true. A machine-written summary saying it here
    would be the promise arriving ahead of the behaviour."""
    summary = research._restart_recovery_patch(INCOG)["summary"].lower()
    for word in ("not saved", "nothing is kept", "deleted", "incognito"):
        assert word not in summary, f"{word!r} is a promise this file may not make"


# ── the consumers: the real recovery coroutines ───────────────────────────

class _Snap:
    def __init__(self, rid, data):
        self.id = rid
        self._d = data

    def to_dict(self):
        return dict(self._d)


class _Query:
    def __init__(self, snaps):
        self._snaps = snaps

    def get(self):
        return list(self._snaps)


class _Col:
    def __init__(self, snaps):
        self._snaps = snaps

    def where(self, *a, **k):
        return _Query(self._snaps)


class _UserRef:
    def __init__(self, db, uid):
        self._db, self._uid = db, uid

    def collection(self, name):
        return _Col(self._db.researches.get(self._uid, []))


class _Users:
    def __init__(self, db):
        self._db = db

    def document(self, uid):
        return _UserRef(self._db, uid)


class _DeviceSnap:
    def __init__(self, data):
        self._d = data
        self.exists = data is not None

    def to_dict(self):
        return dict(self._d or {})


class _Devices:
    def __init__(self, doc):
        self._doc = doc

    def document(self, _id):
        return self

    def get(self):
        return _DeviceSnap(self._doc)


class _FakeDB:
    def __init__(self, researches, device=None):
        self.researches = researches
        self.device = device

    def collection(self, name):
        if name == "devices":
            return _Devices(self.device)
        return _Users(self)


def _recovery_world(monkeypatch, snaps, device=None):
    writes = []
    monkeypatch.setattr(research, "_firebase_db", _FakeDB({UID: snaps}, device))
    monkeypatch.setattr(research, "WORKER_ID", 1, raising=False)
    monkeypatch.setattr(research, "load_worker_count", lambda: 1)
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-1")
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research", lambda rid, wid: [])
    monkeypatch.setattr(research, "_update_research_doc",
                        lambda uid, rid, patch: (writes.append((uid, rid, patch)) or True))
    monkeypatch.setattr(research, "log", lambda *a, **k: None)
    return writes


def test_boot_recovery_ends_a_run_that_keeps_nothing_and_never_resumes_it(monkeypatch):
    """⛔⛔ THE CONSUMER. An auto-resume here would re-open somebody's private
    research hours later on THIS machine's browser profiles, on a computer
    whose owner was told only that a run happened."""
    writes = _recovery_world(monkeypatch, [_Snap(INCOG, {"status": "ongoing"})])
    enqueued = []
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref",
                        types.SimpleNamespace(put_nowait=enqueued.append))
    rehydrated, orphaned = asyncio.run(
        research._rehydrate_ongoing_for_tree(UID, UID, set()))
    assert rehydrated == 0 and orphaned == 1
    assert enqueued == [], "an incognito run was re-enqueued for a resume"
    [(_uid, rid, patch)] = writes
    assert rid == INCOG and patch["status"] == "stopped"


def _supervised_world(monkeypatch, tmp_path, rid):
    """A boot that WOULD auto-resume: a supervised device, a run id the disk
    corroborates, and its queue directory intact."""
    writes = _recovery_world(
        monkeypatch, [_Snap(rid, {"status": "ongoing", "deviceId": "dev-1"})],
        device={"supervised": True})
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    (tmp_path / "queues" / "run-1").mkdir(parents=True)
    monkeypatch.setattr(research, "_corroborated_run_id", lambda *a, **k: "run-1")
    monkeypatch.setattr(research, "load_checkpoint", lambda qd: {"topic": "cats"})
    enqueued = []
    monkeypatch.setattr(research, "_safe_enqueue",
                        lambda q, job, source=None: (enqueued.append(job) or True))
    monkeypatch.setitem(research._QUEUE_STATE, "queue_ref", object())
    return writes, enqueued


def test_a_supervised_boot_still_auto_resumes_an_ordinary_run(tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY, and it is the one that makes the next pin mean
    something: without a boot that really would resume, "it did not resume"
    passes for every reason at once."""
    writes, enqueued = _supervised_world(monkeypatch, tmp_path, CHAT)
    rehydrated, _ = asyncio.run(research._rehydrate_ongoing_for_tree(UID, UID, set()))
    assert rehydrated == 1 and len(enqueued) == 1
    assert enqueued[0]["research_id"] == CHAT
    assert writes == [], "an auto-resumed run must not also be marked"


def test_a_supervised_boot_refuses_to_auto_resume_a_run_that_keeps_nothing(
        tmp_path, monkeypatch):
    """⛔⛔ THE WORST OUTCOME THIS BRANCH REFUSES. An auto-resume re-opens
    somebody's private research on THIS machine's browser profiles — its
    logged-in ChatGPT, Gemini and Claude accounts — hours after they left, on a
    computer whose owner was told only that a run happened."""
    writes, enqueued = _supervised_world(monkeypatch, tmp_path, INCOG)
    rehydrated, orphaned = asyncio.run(
        research._rehydrate_ongoing_for_tree(UID, UID, set()))
    assert enqueued == [], "a run that keeps nothing was re-opened on a shared browser"
    assert rehydrated == 0 and orphaned == 1
    [(_uid, rid, patch)] = writes
    assert rid == INCOG and patch["status"] == "stopped"


def test_boot_recovery_still_parks_an_ordinary_run(monkeypatch):
    """⭐ ACCEPT POLARITY on the same coroutine."""
    writes = _recovery_world(monkeypatch, [_Snap(CHAT, {"status": "ongoing"})])
    asyncio.run(research._rehydrate_ongoing_for_tree(UID, UID, set()))
    [(_uid, rid, patch)] = writes
    assert rid == CHAT and patch["status"] == "paused_backend_restart"


def test_boot_recovery_leaves_a_run_a_live_sibling_is_running(monkeypatch):
    """⛔ THE ORDER MATTERS. The stop sits AFTER every ownership guard, so a run
    another live worker holds is still left alone — stopping it would end a
    paid run that is perfectly healthy."""
    writes = _recovery_world(monkeypatch, [_Snap(INCOG, {"status": "ongoing"})])
    monkeypatch.setattr(research, "_scan_sibling_locks_for_research",
                        lambda rid, wid: [{"worker_id": 2, "pid": 9, "started_at": 0}])
    asyncio.run(research._rehydrate_ongoing_for_tree(UID, UID, set()))
    assert writes == [], "a run a live sibling is executing was stopped"


def test_the_dead_worker_reconciler_ends_a_run_that_keeps_nothing(monkeypatch):
    """The other recovery path — one worker given up on rather than the whole
    process restarting — must reach the same answer."""
    writes = _recovery_world(
        monkeypatch, [_Snap(INCOG, {"status": "ongoing", "assignedWorker": 2})])
    assert asyncio.run(research._reconcile_dead_worker_runs(UID, {2})) == 1
    [(_uid, rid, patch)] = writes
    assert rid == INCOG and patch["status"] == "stopped"


def test_the_dead_worker_reconciler_still_parks_an_ordinary_run(monkeypatch):
    writes = _recovery_world(
        monkeypatch, [_Snap(CHAT, {"status": "ongoing", "assignedWorker": 2})])
    assert asyncio.run(research._reconcile_dead_worker_runs(UID, {2})) == 1
    [(_uid, rid, patch)] = writes
    assert patch["status"] == "paused_backend_restart"


def test_a_stopped_incognito_run_can_no_longer_be_re_enqueued(monkeypatch):
    """⛔ THE STATUS HAS TO BE ONE THE ENQUEUE GUARD REFUSES, or the stop is a
    label and the next boot picks the run up again. `_safe_enqueue`'s whitelist
    is queued / ongoing / paused_backend_restart."""
    assert "stopped" not in research._safe_enqueue.__defaults__[0]
    assert "paused_backend_restart" in research._safe_enqueue.__defaults__[0]
