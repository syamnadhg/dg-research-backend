"""What a PERSON is actually told about a blocked run — sr.py's lines and the
watchdog's proactive push.

⛔⛔ PIN THE CONSUMER, NOT ONLY THE HELPER. The planner in bridge.py is covered by
test_decision_plan_0831.py, but a planner nobody calls is a planner that proves
nothing: these two scripts could go on guessing from `pendingDecision.kind` and
every planner test would stay green. Everything here reads the strings the two
chat surfaces actually emit.

Both scripts are STANDALONE files copied into a chat runtime's skills dir at
connect time — they can sit a release behind the bridge in either direction, so
the skew rules are pinned here too.
"""

import importlib.util
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from facade import bridge

from test_decision_plan_0831 import (  # noqa: E402
    crash_login_interrupt_card,
    crash_loop_card,
    env_card,
    p0_login_card,
)

_SCRIPTS = Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts"


def _load(name: str, alias: str):
    spec = importlib.util.spec_from_file_location(alias, _SCRIPTS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load("sr.py", "sr_copy_under_test")
poll = _load("sr_attention_poll.py", "sr_poll_copy_under_test")


class FakeFS:
    researches: dict = {}
    devices: list = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]
    commands: list = []
    resumes: list = []
    updates: list = []

    def __init__(self, _tp):
        pass

    def list_researches(self, uid, *, page_size=50):
        return [dict(d) for d in FakeFS.researches.values()]

    def list_devices(self, uid):
        return [dict(d) for d in FakeFS.devices]

    def get_research(self, uid, rid):
        d = FakeFS.researches.get(rid)
        return dict(d) if d else None

    def write_command(self, uid, research_id, action, *, device_id, extra=None):
        FakeFS.commands.append({"rid": research_id, "action": action, "extra": extra})
        return "CMD-1"

    def enqueue_resume(self, device_id, *, uid, research_id, backend_run_id, email=""):
        FakeFS.resumes.append({"research_id": research_id,
                               "backend_run_id": backend_run_id, "email": email})
        return "Q-R1"

    def update_research(self, uid, rid, patch, *, delete_fields=None):
        FakeFS.updates.append({"rid": rid, "delete_fields": list(delete_fields or [])})
        d = FakeFS.researches.get(rid)
        if d is not None:
            for f in (delete_fields or []):
                d.pop(f, None)


@pytest.fixture()
def bridge_port(monkeypatch):
    FakeFS.researches = {}
    FakeFS.devices = [{"id": "dev-a", "name": "My PC", "ownerUid": "u1"}]
    FakeFS.commands = []
    FakeFS.resumes = []
    FakeFS.updates = []
    monkeypatch.setattr(bridge, "FirestoreRest", FakeFS)
    monkeypatch.setattr(bridge.prefs, "get_selected_device", lambda uid: None)
    monkeypatch.setattr(bridge.prefs, "set_selected_device", lambda d, uid: None)
    monkeypatch.setattr(bridge.prefs, "clear_selected_device", lambda: None)
    monkeypatch.setattr(bridge.selfupdate, "agent_update_available", lambda **kw: None)
    monkeypatch.setattr(bridge.selfupdate, "latest_on_pypi", lambda pkg, force=False: None)
    state = bridge.BridgeState()
    state.set_session(SimpleNamespace(uid="u1", email="e@x.y",
                                      id_token=lambda force=False: "tok"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), bridge._make_handler(state))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("SR_BRIDGE_PORT", str(port))
    monkeypatch.setattr(sr, "_base", lambda: f"http://127.0.0.1:{port}")
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()


def _seed(rid="r1", *, card=None, status="ongoing", brid="run-9", title="EV market"):
    # viaAgent: the `updates` command asks the bridge for agent-started runs
    # only, so a fixture without it is filtered out before any copy is built.
    doc = {"id": rid, "title": title, "status": status, "phase": 2,
           "links": {}, "deviceId": "dev-a", "backendRunId": brid,
           "viaAgent": True}
    if card is not None:
        doc["pendingDecision"] = card
    FakeFS.researches[rid] = doc
    return doc


# ── (a) the API-key card, on the surface where the wrong line fired ──────────

def test_status_of_an_env_card_asks_for_an_api_key_not_a_sign_in(bridge_port, capsys):
    """⛔⛔ THE OWNER'S WORDS: "If the run actually needs an API key, it should ask
    for an API key." It used to print "→ sign in on the device" underneath a
    headline that correctly said the run needed an Anthropic key — two sentences
    contradicting each other, and the person followed the wrong one."""
    _seed(card=env_card())
    assert sr.main(["status", "r1"]) == 0
    out = capsys.readouterr().out
    assert "API key" in out
    assert "sign in on the device" not in out.lower()


def test_status_of_a_real_sign_in_wall_still_says_sign_in(bridge_port, capsys):
    """The other half of the owner's ask, and the over-correction guard."""
    _seed(card=p0_login_card())
    assert sr.main(["status", "r1"]) == 0
    out = capsys.readouterr().out
    assert "Sign in" in out and "API key" not in out


def test_updates_uses_the_bridge_action_not_a_kind_guess(bridge_port, capsys):
    """The /updates path never carried pendingDecision at all, so its action line
    was the generic "retry or skip" for every card — including the env card."""
    _seed(card=env_card())
    assert sr.main(["updates"]) == 0
    out = capsys.readouterr().out
    assert "API key" in out
    assert "skip to move past it" not in out


# ── (d) the discarded sentence ───────────────────────────────────────────────

def test_the_cards_own_instruction_is_shown(bridge_port, capsys):
    """⛔ The crash card's headline is "Paused by the login command" — three
    words. The sentence telling you to sign back in FIRST lives in `details`, and
    chat dropped it for every card."""
    _seed(card=crash_login_interrupt_card())
    assert sr.main(["status", "r1"]) == 0
    out = capsys.readouterr().out
    assert "resumes from its checkpoint" in out


# ── (c) naming only the verbs that work ──────────────────────────────────────

def test_retry_is_refused_locally_when_the_card_has_no_retry(bridge_port, capsys):
    """Same discrimination as the skip case: the route's own 409 body carries the
    phrase too, so pin the local sentence."""
    from test_decision_plan_0831 import noretry_card
    _seed(card=noretry_card())
    assert sr.main(["retry", "r1"]) == 1
    out = capsys.readouterr().out
    assert "“EV market” has no Retry right now." in out
    assert "couldn’t retry" not in out, "it round-tripped instead of refusing locally"
    assert FakeFS.commands == [] and FakeFS.resumes == []


def test_skip_is_refused_when_the_card_has_no_skip(bridge_port, capsys):
    """⛔ ASSERT THE LOCAL FORM, NOT JUST THE WORDS. The ROUTE's 409 body also
    contains "has no Skip", so an assertion on that phrase alone was satisfied
    whether or not sr.py checked first — mutation testing removed the local check
    and this test stayed green. The two outputs differ: the local refusal names
    the run and what to do, the round-trip prefixes "✗ couldn't skip…"."""
    _seed(card=crash_login_interrupt_card())
    assert sr.main(["skip", "--run", "r1"]) == 1
    out = capsys.readouterr().out
    assert "“EV market” has no Skip right now." in out
    assert "couldn’t skip" not in out, "it round-tripped instead of refusing locally"
    assert FakeFS.commands == [] and FakeFS.updates == []


def test_the_refusal_names_what_to_do_instead(bridge_port, capsys):
    _seed(card=crash_login_interrupt_card())
    sr.main(["skip", "--run", "r1"])
    assert "last checkpoint" in capsys.readouterr().out


# ── (b) not overclaiming a resume ────────────────────────────────────────────

def test_a_checkpoint_retry_says_it_asked_rather_than_that_it_resumed(bridge_port, capsys):
    """⛔ A queue resume is a REQUEST to the research computer. It re-enqueues
    from disk and can still decline — pruned artifacts, a run marked stopped —
    without telling us. "Retrying — resuming the run" claimed an outcome this
    side cannot see."""
    _seed(card=crash_loop_card())
    assert sr.main(["retry", "r1"]) == 0
    out = capsys.readouterr().out
    assert "Asked your computer" in out and "last checkpoint" in out
    assert len(FakeFS.resumes) == 1 and FakeFS.commands == []


def test_a_plain_retry_keeps_todays_wording(bridge_port, capsys):
    _seed(card=p0_login_card())
    assert sr.main(["retry", "r1"]) == 0
    assert "Retrying" in capsys.readouterr().out
    assert FakeFS.commands[-1]["action"] == "retry_phase"


def test_discarding_a_crash_card_says_the_run_stays_stopped(bridge_port, capsys):
    _seed(card=crash_loop_card())
    assert sr.main(["skip", "--run", "r1"]) == 0
    out = capsys.readouterr().out
    assert "stays stopped" in out
    assert FakeFS.updates and FakeFS.updates[-1]["delete_fields"] == ["pendingDecision"]


# ── version skew: these scripts ship on their own schedule ───────────────────

def test_an_older_bridge_falls_back_to_the_legacy_tail():
    """No attentionAction on the row → today's guess, unchanged."""
    row = {"needsAttention": True, "attention": "Hit a snag",
           "pendingDecision": {"kind": "pipeline_error"}}
    lines = sr._attention_lines(row)
    assert lines[-1] == ("  → tell me to retry to resume, or skip to move past it "
                         "(or open the app).")


def test_the_legacy_branch_still_fixes_the_api_key_case():
    """The one line the old guess got outright wrong is corrected client-side too,
    so (a) lands even against a bridge that has not been updated."""
    row = {"needsAttention": True, "attention": "needs a key",
           "pendingDecision": env_card()}
    assert "API key" in sr._attention_lines(row)[-1]


def test_absent_offers_is_not_empty_offers():
    """⛔⛔ THE LOAD-BEARING SKEW RULE. ABSENT means "an older bridge, assume
    both". PRESENT-AND-EMPTY means "neither works". A script that conflates them
    refuses every action against an older bridge and goes silent."""
    assert sr._refuse_if_not_offered({"title": "x"}, "retry") is None
    assert sr._refuse_if_not_offered({"title": "x", "attentionOffers": []},
                                     "retry") is not None
    assert sr._refuse_if_not_offered({"title": "x", "attentionOffers": ["retry"]},
                                     "retry") is None


# ── the proactive push ───────────────────────────────────────────────────────

def _run(rid="r1", **kw):
    row = {"runId": rid, "title": "EV market", "status": "ongoing",
           "phaseUpdates": [], "needsAttention": True, "attention": "Hit a snag"}
    row.update(kw)
    return row


def test_the_pushed_line_names_only_the_offered_verbs():
    """⛔ The watchdog posted "reply retry to resume or skip to move past it" for
    EVERY blocker — including the card whose Skip terminated the run, and the two
    where neither verb existed. It is the surface a person is told about a
    blocker without asking, so it is the one that must not offer a wrong button."""
    plan = bridge._decision_plan(crash_login_interrupt_card())
    act, det, offers = bridge._attention_extras(plan)
    line = poll._attention_line(_run(attentionAction=act, attentionDetails=det,
                                     attentionOffers=offers))
    assert "no skip on this one" in line
    assert "“skip” to move past it" not in line


def test_the_pushed_line_carries_the_cards_own_sentence():
    plan = bridge._decision_plan(crash_loop_card())
    act, det, _ = bridge._attention_extras(plan)
    line = poll._attention_line(_run(attentionAction=act, attentionDetails=det))
    assert "didn't take" in line and "last checkpoint" in line


def test_the_pushed_line_has_no_markdown():
    """This file posts DIRECTLY to the origin channel with no runtime to
    reformat, and that channel may be SMS — where `[x](y)` shows as brackets."""
    plan = bridge._decision_plan(env_card())
    act, det, _ = bridge._attention_extras(plan)
    line = poll._attention_line(_run(attentionAction=act, attentionDetails=det))
    for ch in ("**", "](", "`", "__"):
        assert ch not in line, ch


def test_an_older_bridge_keeps_the_old_pushed_tail():
    line = poll._attention_line(_run())
    assert line.endswith("(or open the app).")
    assert "\n" not in line


def test_a_second_blocker_with_the_same_reason_is_still_announced():
    """⛔⛔ THE SWALLOWED NOTICE. The change-detect key was the reason text alone,
    so two different cards on one run that render the same sentence produced NO
    push at all for the second — the run sat blocked, in silence."""
    first = _run(attention="Hit a snag", attentionAction="Reply “retry” to resume.")
    msgs, state = poll.compute([first], {})
    assert len(msgs) == 1
    second = _run(attention="Hit a snag",
                  attentionAction="Reply “skip” to drop Claude from this run.")
    msgs2, _ = poll.compute([second], state)
    assert len(msgs2) == 1, "the second, different blocker was swallowed"


def test_an_unchanged_blocker_is_not_re_announced():
    row = _run(attentionAction="Reply “retry” to resume.")
    msgs, state = poll.compute([row], {})
    assert len(msgs) == 1
    msgs2, _ = poll.compute([row], state)
    assert msgs2 == []


def test_a_state_file_from_an_older_script_does_not_re_announce_everything():
    """⛔ The old state has no "akey". Comparing the new two-part key against it
    would differ for every tracked run and re-announce every live blocker once,
    on the first tick after an update — a burst of notices for nothing new."""
    old_state = {"r1": {"announced": [], "needs": True, "attention": "Hit a snag",
                        "ended": False, "completed": False}}
    row = _run(attention="Hit a snag", attentionAction="Reply “retry” to resume.")
    msgs, new_state = poll.compute([row], old_state)
    assert msgs == []
    assert new_state["r1"]["akey"] == poll._attention_key(row)
