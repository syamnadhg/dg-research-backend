"""The no-computer screen reaches the person intact — in band, and everywhere it ends.

⭐⭐ MEASURED, NOT GUESSED (owner, 2026-09-21). Asked "Add device to my Super
Research", the chat ran `status-account` AND `devices`. Both printed this screen
exactly as designed — state of play, "Add a computer:", the public computers as a
named section with its list, the install walkthrough last. The reply the person
got dropped the section heading, demoted the list to an "Alternatively…" aside,
led with `superresearch --pair` in a fenced block, and lost the walkthrough link.

⛔⛔ AND THAT FENCED BLOCK WAS NOT IMPROVISED — SKILL.md PRESCRIBED IT. Its "wants
to add a computer but hasn't given a code" recipe said to ask for the code and
then showed exactly that block; its formatting rule said to fence every setup
command; its routing row sent a code-less "add a device" to `device-add <code>`,
which cannot run. An in-band rule fighting a written recipe is a coin toss, so all
of those are pinned here too. (The first version of this file called the block
"of its own invention"; an adversarial review of SKILL.md showed it was not.)

⛔ IN BAND BECAUSE PROSE ALREADY FAILED. The rule rides under `_AGENT_ONLY_MARKER`,
attached to the bytes it governs, like the send-logs plan's rule.

⛔⛔ AND ONLY WHERE THE MESSAGE ENDS. Everything below the marker is hidden from
the person, so the block must be the LAST thing printed; the shared renderer is
also returned as a FRAGMENT that other code extends, so the rule never lives
inside it.
"""

import contextlib
import io
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from tests.conftest import code_only

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "facade" / "skill" / "scripts"))
import sr  # noqa: E402

SKILL = Path(__file__).resolve().parents[1] / "facade" / "skill" / "SKILL.md"
SRC = Path(sr.__file__).read_text(encoding="utf-8")
M = sr._AGENT_ONLY_MARKER
PUB = {"devices": [{"deviceId": "d1", "label": "Macbook", "online": False,
                    "full": False}], "truncated": False}


def _get_empty(path, timeout=None):
    if path == "/status":
        return 200, {"authed": True, "email": "s@x.y", "agentUpdate": "0.1.34"}
    if path == "/devices":
        return 200, {"devices": [], "selectedDeviceId": None}
    if path.startswith("/devices/public"):
        return 200, PUB
    return 200, {}


@pytest.fixture()
def empty_account(monkeypatch):
    monkeypatch.setattr(sr, "_get", _get_empty)
    monkeypatch.setattr(sr, "_post", lambda p, b=None, timeout=None: (
        400, {"reason": "no_devices", "error": "no devices yet"}))
    monkeypatch.setattr(sr, "_origin_from_env",
                        lambda: {"platform": "hermes", "chat_id": "c1"})


def _run(fn, ns):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(ns)
    return buf.getvalue()


def _login_done(monkeypatch):
    """The usual first-time path: signed in just now, a topic, no computer.
    ⚠ 2026-09-25: the note arrives through `POST /signin/ack` (with its news), and
    a "connected" flow counts only while `authed` says so."""
    note = {"ts": 1, "email": "s@x.y", "needsDevice": True, "topic": "creativity",
            "pendingTopic": ""}

    def _post(p, b=None, timeout=None):
        if p == "/signin/ack":
            return 200, {"ok": True, "authed": True, "email": "s@x.y",
                         "consumed": True, "signedIn": note}
        return 200, {"state": "connected", "authed": True, "email": "s@x.y",
                     "pendingTopic": "creativity"}
    monkeypatch.setattr(sr, "_post", _post)
    return sr.cmd_login_wait, NS(json=False)


# ⚠ 2026-09-25 (owner): `status-account` left this table — a login answer is
# about login only, so it prints no screen and needs no rule.
SITES = {
    "devices": lambda mp: (sr.cmd_devices, NS(json=False)),
    "research": lambda mp: (sr.cmd_research, NS(json=False, topic="creativity",
                                                device="", no_video=False,
                                                no_email=False)),
    # ⛔ the review found this one uncovered — the likeliest place a NEW person
    # meets the screen at all
    "login-done": _login_done,
    # every device command whose name lookup found no computer goes through the
    # same source; device-use stands for device-remove and device-visibility
    "device-use": lambda mp: (sr.cmd_device_use, NS(json=False, device="Macbook")),
}


@pytest.mark.parametrize("name", list(SITES))
def test_every_message_that_ends_on_the_empty_state_carries_the_rule(
        empty_account, monkeypatch, name):
    fn, ns = SITES[name](monkeypatch)
    out = _run(fn, ns)
    assert out.count(M) == 1, f"{name}: exactly one marker block, got {out.count(M)}"
    assert sr._EMPTY_STATE_RELAY in out.split(M, 1)[1], name


@pytest.mark.parametrize("name", list(SITES))
def test_the_rule_is_last_and_hides_nothing_the_person_needs(empty_account, monkeypatch, name):
    """⛔⛔ BELOW THE MARKER IS INVISIBLE. Every part of the screen sits above it."""
    fn, ns = SITES[name](monkeypatch)
    above, _, below = _run(fn, ns).partition(M)
    # ⚠ REPINNED 2026-09-24: the add line IS the code sentence and carries the
    # link (owner) — "It gives you an 8-char access code" is gone from every screen.
    for must_see in (sr._ADD_A_COMPUTER, sr._PUBLIC_HEAD, "Macbook",
                     "superresearch.io/install"):
        assert must_see in above, f"{name}: {must_see!r} fell below the marker"
    assert "It gives you" not in above, name
    # ⛔ and the screen itself never hands the person `--pair` (owner, 2026-09-23)
    assert "superresearch --pair" not in above, name
    assert below.strip().startswith("⛔ Relay the screen above"), below[:120]
    # ⛔ AND THE RULE IS THE LAST THING PRINTED — nothing follows it
    assert below.rstrip().endswith(sr._EMPTY_STATE_RELAY), below[-200:]


def test_the_held_topic_promise_stays_visible(empty_account, monkeypatch):
    """The sign-in path's lead says the topic has nowhere to run yet; the research
    path's says it is being held. Either must reach the person."""
    fn, ns = SITES["login-done"](monkeypatch)
    above = _run(fn, ns).partition(M)[0]
    assert "creativity" in above


def test_the_update_notice_stays_visible(empty_account):
    # ⚠ 2026-09-25 (owner): status-account prints no screen and so no marker at
    # all now — the notice is simply there, after the sign-in line.
    out = _run(sr.cmd_status_account, NS(json=False))
    assert "0.1.34" in out and M not in out, out


def test_the_rule_is_short_carries_the_url_and_names_the_codes_origin():
    """⛔ THE RULE ONCE SAID "walkthrough LAST" while status-account prints an update
    notice after it — a literal reading would drop the notice. Its replacement
    named every line before and after the screen and was long enough that the
    2026-09-24 relay dropped the link with it sitting in the tool output: it could
    NAME the link but never put one back, and said nothing about where the code
    comes from, so the model invented "from the Super Research app".

    ⭐ THE RULE THAT REPLACED IT (owner, 2026-09-24): as printed, the URL written
    into the rule itself so a model can restore it, the public section kept whole,
    the code's true origin stated, and no commands added."""
    r = sr._EMPTY_STATE_RELAY
    assert "LAST" not in r
    # the URL, literally — a rule that only names "the install link" cannot
    # restore one a relay dropped
    assert sr._INSTALL_PAGE_URL in r
    assert "“Add a computer”" in r
    assert f"“{sr._PUBLIC_HEAD}”" in r and "every row" in r
    assert "as printed" in r
    assert "comes from the person's computer" in r
    assert "never say it comes from the app" in r
    assert "`superresearch --pair`" in r and "add no commands" in r
    # ⛔ SHORT: the long ordering clause it replaced is gone
    assert "then the install link" not in r and "update notice" not in r
    assert len(r) < 400, len(r)


def test_the_shared_renderer_never_carries_the_marker(empty_account):
    assert M not in "\n".join(sr._no_device_lines())
    assert M not in "\n".join(sr._no_device_lines(lead="“x” has nowhere to run yet."))


def test_a_fragment_caller_keeps_its_own_line_visible(monkeypatch):
    """send-logs with no computer appends an offer of the agent's own log after
    the screen. It must stay visible, so no marker may precede it."""
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (
        (400, {"reason": "no_devices", "error": "no devices"})
        if p.startswith("/logs/runs") else
        (200, PUB) if p.startswith("/devices/public") else
        (200, {"devices": []})))
    out = _run(sr.cmd_send_logs, NS(json=False, confirm=False, runs="", machine=False,
                                    agent_log=False, device="", none=False,
                                    status="", list=False))
    line = next((ln for ln in out.splitlines() if "agent itself" in ln), None)
    assert line is not None, out
    if M in out:
        assert out.index(line) < out.index(M), "the agent-log offer fell below a marker"


def test_the_json_path_is_untouched(empty_account):
    assert M not in _run(sr.cmd_devices, NS(json=True))


# ── the populated account: "add a device" must still be answerable ───────────

def test_a_populated_device_list_names_the_code_route(monkeypatch):
    """⛔⛔ A NO-CODE "add a device" NOW LANDS ON `devices` FOR EVERYONE. For
    somebody who already has a computer, a list that closes on "you can add …
    anytime — just ask" restates the question they just asked. It names the
    route instead — and with no marker, because nothing here is being relayed."""
    monkeypatch.setattr(sr, "_get", lambda p, timeout=None: (200, {
        "devices": [{"id": "m1", "name": "Studio Mac", "role": "owner"}],
        "selectedDeviceId": "m1"}))
    out = _run(sr.cmd_devices, NS(json=False))
    assert sr._ADD_A_COMPUTER in out
    # ⚠ AND 2026-09-24: with the install link — somebody whose only computer is
    # shared, or who wants a second one, lands here too (owner)
    assert "https://superresearch.io/install" in out
    assert "You can add, remove, or switch devices anytime" not in out
    assert M not in out


def test_the_add_with_a_code_sentence_has_one_source():
    """⛔ NEVER A SECOND WORDING — retyping it is the drift the shared empty state
    was written to end.

    ⚠ REPINNED 2026-09-24 to the new sentence, and to the CODE: the old count read
    raw source, where a comment quoting the line would have counted too."""
    code = code_only(SRC)
    assert code.count("Add a computer: set one up at") == 1
    # the retired wordings are gone from the code, not just from one screen
    for gone in ("paste the access code from any computer",
                 "Don't have your own Research Computer yet",
                 "It gives you an 8-char access code"):
        assert gone not in code, gone


def test_the_owners_exact_words_reach_the_device_screen():
    """The measured request, verbatim."""
    argv, _ = sr._nl_resolve("Add device to my Super Research")
    assert argv == ["devices"]
    # and a message that CARRIES a code still pairs at once
    assert sr._nl_resolve("add a device K7XQ9B2M")[0] == ["device-add", "K7XQ9B2M"]


# ── SKILL.md must not prescribe the reply the rule forbids ───────────────────

def test_skill_md_no_longer_licenses_skipping_the_block():
    text = SKILL.read_text(encoding="utf-8")
    assert "silently skip the block" not in text
    assert "This is the ONLY thing below the" not in text
    assert "Silently skip only that tool call" in text
    assert "a relay rule below the marker still" in text


def test_skill_md_no_longer_prescribes_the_failed_reply():
    """⛔⛔ THE BLOCKER THE REVIEW FOUND. The no-code recipe told the model to ask
    for the code and then showed a fenced `--pair` block — the measured reply,
    almost word for word, and a reply made WITHOUT running the client, so the
    in-band rule would never even have been seen."""
    text = SKILL.read_text(encoding="utf-8")
    assert "ask them to **paste the" not in text
    assert "hasn't given a code, run `sr.py devices`" in text
    assert "explicitly ask how to set up a machine" in text


def test_skill_md_routes_a_codeless_request_to_a_command_that_can_run():
    """`device-add` requires a code; a request without one had nothing to run."""
    text = SKILL.read_text(encoding="utf-8")
    assert '"add a device" — **no code in the message** | `sr.py devices`' in text
    assert 'dashes optional), or "add a device", means run' not in text


def test_skill_md_no_longer_calls_this_screen_a_pairing_step():
    text = SKILL.read_text(encoding="utf-8")
    for gone in ("pair-a-device step", "walk the pair-a-computer steps",
                 "pair-a-device prompt", "in a fenced code block, never inline"):
        assert gone not in text, gone
    assert "lines the client printed, as printed" in text
    # ⚠ INVERTED 2026-09-25 (owner): the bare-/sr branch that relayed this screen
    # from `status-account` is gone with the screen — a login answer is about
    # login only, and a research with no computer says so itself.
    assert "**Signed in, no computer yet**" not in text
