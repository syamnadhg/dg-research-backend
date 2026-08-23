"""Wave 5: a missing dependency is not a network problem.

⛔⛔ WHAT IT DID. `init_firebase` classified a failed `from auth import …` as
`"transient"`, with the comment "import hiccup — let reconnect retry". A package
that is not on disk is not a hiccup, and no number of retries puts a file back.
So the reconnect ladder ran 5→10→30s for as long as the machine stayed on,
writing "could not reach Google — retrying" about a network that was fine.

⛔⛔ AND IT REACHED THE ONE COMMAND A STUCK PERSON IS TOLD TO RUN. `--doctor`
reads the same field, so on a broken install it printed

    ✗ Cannot reach firestore.googleapis.com
        the network, not your pairing — nothing here needs re-pairing

then probed all four hosts, found every one of them healthy, printed "The network
path is fine — every host this machine needs resolves and accepts a connection",
and handed over an EMPTY action list. A diagnosis, a contradiction of it, and
nothing to do.

⚠ "TERMINAL" IS ABOUT WHAT THE PERSON IS TOLD, NOT ABOUT NEVER LOOKING AGAIN.
A backend acquires the missing file two ways with nobody touching it — the
person runs the repair command, or an `--update` that was replacing
site-packages when this process looked finishes. Both should heal without a
restart. So the ladder stops, the remedy is said once, and the re-check is slow
enough that nobody could read it as retrying — and the message says out loud
that it re-checks, rather than leaving one nobody was told about.

Run: pytest tests/test_broken_install_terminal_0822.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from conftest import code_only_deep  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
#  1. the classification
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def auth_import_fails(monkeypatch):
    """Make `from auth import …` raise the way a half-written install does.

    ⭐ `sys.modules[name] = None` is the stdlib's own marker for "this import
    fails"; the import machinery raises ImportError on it. Nothing on disk is
    touched, and the real `init_firebase` runs against it."""
    monkeypatch.setitem(sys.modules, "auth", None)
    monkeypatch.setattr(research, "_firebase_db", None, raising=False)
    monkeypatch.setattr(research, "_firebase_down_reason", None, raising=False)


class TestWhatABrokenImportIsCalled:

    def test_init_firebase_reports_a_broken_install(self, auth_import_fails):
        assert research.init_firebase() is False
        assert research._firebase_down_reason == "broken_install"

    def test_it_is_not_called_transient(self, auth_import_fails):
        """⛔⛔ THE WHOLE DEFECT IN ONE ASSERTION. `transient` is what routes
        this into a retry ladder that cannot succeed and a doctor branch that
        blames the network."""
        research.init_firebase()
        assert research._firebase_down_reason != "transient"

    def test_it_is_not_called_revoked_either(self, auth_import_fails):
        """`revoked` would send the person to re-pair, spending a pairing that
        is perfectly good — the 2026-08-17 defect, in a new place."""
        research.init_firebase()
        assert research._firebase_down_reason != "revoked"

    def test_the_line_says_the_install_rather_than_the_network(
            self, auth_import_fails, capsys):
        research.init_firebase()
        out = capsys.readouterr().out
        assert "install" in out.lower()
        # ⚠ Not the bare word "retrying" — this line legitimately says
        # "retrying cannot complete it", which is the point. What must be gone
        # are the sentences that name the NETWORK as the fault.
        for claim in ("could not reach google", "network error",
                      "firestore unreachable", "retrying in"):
            assert claim not in out.lower(), (
                f"the import failure still blames the network: {claim!r}")

    def test_the_line_names_the_exception(self, auth_import_fails, capsys):
        """A support bundle that says "cannot import" without saying what
        failed cannot tell a missing package from a broken one.

        ⚠ The type here is `ModuleNotFoundError`, not `ImportError` — it is a
        subclass, and the handler records the real class rather than the one it
        catches. My first version of this asserted the base name and was wrong
        about the code, not the other way round."""
        research.init_firebase()
        out = capsys.readouterr().out
        assert "ModuleNotFoundError" in out
        assert "auth" in out

    def test_a_healthy_import_is_untouched(self, monkeypatch):
        """⛔ The guard has to be able to NOT fire. `auth` imports fine in this
        tree, so a run that gets past it must reach the keystore question."""
        monkeypatch.setattr(research, "_firebase_db", None, raising=False)
        monkeypatch.setattr(research, "_firebase_down_reason", None, raising=False)
        research.init_firebase()
        assert research._firebase_down_reason != "broken_install"

    def test_the_word_transient_is_gone_from_that_handler(self):
        src = code_only_deep(research.init_firebase)
        handler = src.split("except ImportError", 1)
        assert len(handler) == 2, "the ImportError handler has been reshaped"
        body = handler[1].split("return False", 1)[0]
        assert '"transient"' not in body
        assert '"broken_install"' in body


# ══════════════════════════════════════════════════════════════════════════
#  2. what it says
# ══════════════════════════════════════════════════════════════════════════

class TestTheNotice:

    def test_it_names_the_command_that_repairs_this_install(self):
        assert research._remedy_reinstall() in " ".join(
            research._broken_install_notice())

    def test_the_remedy_is_not_a_second_opinion(self):
        """⛔ Four messages once prescribed `pip install -r requirements.txt` on
        installs that have no such file. There is one author of that sentence and
        this reads from it."""
        src = code_only_deep(research._broken_install_notice)
        assert "_remedy_reinstall()" in src
        assert "pipx install" not in src and "pip install" not in src

    def test_it_says_the_network_and_the_pairing_are_fine(self):
        """⭐ The two things the old behaviour blamed. Saying it is what stops
        someone spending an afternoon on their VPN or re-pairing a good device."""
        text = " ".join(research._broken_install_notice()).lower()
        assert "network is fine" in text
        assert "pairing is fine" in text

    def test_it_says_retrying_cannot_fix_it(self):
        text = " ".join(research._broken_install_notice()).lower()
        assert "retrying cannot fix" in text

    def test_it_says_how_long_until_it_looks_again(self):
        """⚠ THE HONEST HALF. It does re-check, so it says so — a stand-down
        that quietly retries is another message that does not match the code."""
        text = " ".join(research._broken_install_notice())
        assert "re-checks every 10 minutes" in text

    def test_the_interval_is_read_from_the_constant_not_written_out(self):
        """⛔ A literal here drifts the moment the constant moves, and the drift
        is invisible: both halves still read like sentences."""
        assert "re-checks every 1 minute" in " ".join(
            research._broken_install_notice(recheck_s=60))
        assert "re-checks every 2 minutes" in " ".join(
            research._broken_install_notice(recheck_s=120))

    def test_it_hands_over_the_way_every_other_failure_does(self):
        assert research._doctor_share_logs_line() in " ".join(
            research._broken_install_notice())

    def test_every_line_is_its_own_line(self):
        """`log()` is one print per call, so an embedded newline leaves a record
        with no timestamp and no level."""
        lines = research._broken_install_notice()
        assert lines and all("\n" not in x for x in lines)
        assert all(x.startswith("[install] ") for x in lines)


# ══════════════════════════════════════════════════════════════════════════
#  3. the loop actually stands down
# ══════════════════════════════════════════════════════════════════════════

class _StopLoop(Exception):
    pass


async def _run_passes(monkeypatch, passes: int, *, init_returns=False,
                      running=False):
    """Drive the REAL reconnect loop for `passes` iterations, then cancel it.

    ⭐ The loop is the consumer, and the consumer is what this fix changes — a
    helper tested on its own would say nothing about whether the ladder below
    still runs. `asyncio.sleep` is the only thing every path through it has in
    common, so counting it is what bounds the run."""
    seen = {"init": 0, "recover": []}
    left = {"n": passes}

    async def fake_sleep(_secs):
        left["n"] -= 1
        if left["n"] <= 0:
            raise asyncio.CancelledError()

    def fake_init():
        seen["init"] += 1
        return init_returns

    async def fake_recover(reason):
        seen["recover"].append(reason)

    monkeypatch.setattr(research, "_firebase_db", None, raising=False)
    monkeypatch.setattr(research, "_firebase_down_reason", "broken_install",
                        raising=False)
    monkeypatch.setattr(research, "init_firebase", fake_init)
    monkeypatch.setattr(research, "_recover_after_reconnect", fake_recover)
    monkeypatch.setattr(research, "_QUEUE_STATE", {"running": running},
                        raising=False)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await research._firebase_reconnect_loop()
    return seen


class TestTheLoopStandsDown:

    @pytest.mark.asyncio
    async def test_the_retry_ladder_never_runs(self, monkeypatch, capsys):
        """⛔⛔ THE LINE THIS FIX EXISTS TO STOP. 4,921 identical copies of it sit
        in the live corpus."""
        await _run_passes(monkeypatch, 6)
        out = capsys.readouterr().out
        assert "retrying in" not in out
        assert "unreachable for" not in out
        # ⚠ Not a bare "cannot reach": the stand-down notice itself says this
        # backend cannot reach the web app, which is true and is the point. The
        # ladder's own sentences are what must be absent.
        assert "could not reach google" not in out.lower()
        # ⚠ Not a bare "[reconnect]": the loop's own arming line carries that
        # tag at DEBUG and always has. What must be absent is any WARN from it —
        # every one of those is the ladder reporting an attempt.
        assert "[WARN] [reconnect]" not in out
        assert "[reconnect] Firestore" not in out

    @pytest.mark.asyncio
    async def test_the_remedy_is_said(self, monkeypatch, capsys):
        await _run_passes(monkeypatch, 3)
        out = capsys.readouterr().out
        assert research._remedy_reinstall() in out
        assert "install on this computer is incomplete" in out

    @pytest.mark.asyncio
    async def test_it_is_said_once_and_not_on_every_pass(self, monkeypatch, capsys):
        """⛔ A message printed on a five-second loop is not a message. The
        outage notice next door has a repeat timer for exactly this reason; a
        broken install does not clear on its own, so once is right."""
        await _run_passes(monkeypatch, 8)
        out = capsys.readouterr().out
        assert out.count("install on this computer is incomplete") == 1

    @pytest.mark.asyncio
    async def test_the_first_look_is_immediate(self, monkeypatch):
        """Someone who repaired it a second before this branch was reached
        should not wait ten minutes to find out."""
        seen = await _run_passes(monkeypatch, 2)
        assert seen["init"] == 1

    @pytest.mark.asyncio
    async def test_and_then_it_stops_looking_for_a_long_time(self, monkeypatch):
        """⛔⛔ THE INFINITE RETRY, MEASURED. Eight passes of the loop is forty
        seconds of wall clock; the old code would have called init eight times
        and printed eight lines about the network."""
        seen = await _run_passes(monkeypatch, 8)
        assert seen["init"] == 1, (
            f"it looked {seen['init']} times in eight passes — that is a ladder")

    @pytest.mark.asyncio
    async def test_a_repair_is_picked_up_without_a_restart(self, monkeypatch, capsys):
        seen = await _run_passes(monkeypatch, 3, init_returns=True)
        assert seen["init"] == 1
        assert seen["recover"] == ["the install was repaired"]
        assert "missing package is back" in capsys.readouterr().out

    @pytest.mark.asyncio
    async def test_a_repair_mid_run_is_deferred_rather_than_respawned(
            self, monkeypatch):
        """⛔ `_recover_after_reconnect` exits the process when supervised, and a
        local `/api/runs` submit can start a run with no Firestore at all. Same
        deferral the reconnect path takes."""
        seen = await _run_passes(monkeypatch, 3, init_returns=True, running=True)
        assert seen["recover"] == [], "it respawned on top of a live run"

    @pytest.mark.asyncio
    async def test_the_loop_keeps_ticking_for_the_watchdog(self, monkeypatch):
        """The supervisor's per-worker liveness pulse is bumped by this loop. A
        stand-down that stopped ticking would read as a wedged event loop and
        get the worker force-respawned."""
        monkeypatch.setattr(research, "_last_loop_tick_ms", 0, raising=False)
        await _run_passes(monkeypatch, 3)
        assert research._last_loop_tick_ms > 0

    @pytest.mark.asyncio
    async def test_a_transient_outage_still_gets_its_ladder(
            self, monkeypatch, capsys):
        """⛔ THE GUARD ON THE FIX. Standing down is right for a missing file and
        wrong for a network blip, which self-heals in seconds."""
        monkeypatch.setattr(research, "_firestore_down_since_ts", None,
                            raising=False)
        seen = {"n": 0}
        left = {"n": 4}

        async def fake_sleep(_s):
            left["n"] -= 1
            if left["n"] <= 0:
                raise asyncio.CancelledError()

        def fake_init():
            seen["n"] += 1
            return False

        monkeypatch.setattr(research, "_firebase_db", None, raising=False)
        monkeypatch.setattr(research, "_firebase_down_reason", "transient",
                            raising=False)
        monkeypatch.setattr(research, "init_firebase", fake_init)
        monkeypatch.setattr(research, "_QUEUE_STATE", {"running": False},
                            raising=False)
        monkeypatch.setattr(asyncio, "sleep", fake_sleep)
        await research._firebase_reconnect_loop()
        assert seen["n"] >= 3, "the transient ladder stopped climbing"
        assert "retrying in" in capsys.readouterr().out


# ══════════════════════════════════════════════════════════════════════════
#  4. the doctor stops blaming the network
# ══════════════════════════════════════════════════════════════════════════

def _doctor_src() -> str:
    return code_only_deep(research.run_doctor)


def test_the_doctor_has_a_branch_for_a_broken_install():
    """⚠ `run_doctor` cannot be executed in a test — it opens a Firestore
    client, imports patchright and spawns a 60-second Chromium probe. What is
    pinnable is that the branch exists, sits ahead of the network one, and does
    not fall into it."""
    src = _doctor_src()
    assert 'elif _firebase_down_reason == "broken_install":' in src


def test_it_is_decided_before_the_network_branch():
    """⛔⛔ ORDER IS THE WHOLE FIX. Behind the transient branch this case reaches
    the host probes, which all pass, and the reader is told their network is
    fine immediately after being told a host is unreachable."""
    src = _doctor_src()
    assert (src.index('elif _firebase_down_reason == "broken_install":')
            < src.index('elif _firebase_down_reason == "transient":'))


def test_the_broken_install_branch_does_not_probe_the_network():
    src = _doctor_src()
    branch = src.split('elif _firebase_down_reason == "broken_install":', 1)[1]
    branch = branch.split('elif _firebase_down_reason == "transient":', 1)[0]
    for network_thing in ("_probe_host", "_network_verdict", "_DOCTOR_NET_TARGETS"):
        assert network_thing not in branch, (
            f"the broken-install branch still runs {network_thing}")


def test_the_branch_hands_over_the_repair_command():
    """⛔ The founding complaint about this command was a diagnosis with no next
    step, and an empty action list is exactly what it produced here."""
    src = _doctor_src()
    branch = src.split('elif _firebase_down_reason == "broken_install":', 1)[1]
    branch = branch.split('elif _firebase_down_reason == "transient":', 1)[0]
    assert "manual_actions.append(_remedy_reinstall())" in branch


def test_it_is_a_failure_not_a_warning():
    """Nothing on this machine works until it is repaired."""
    src = _doctor_src()
    branch = src.split('elif _firebase_down_reason == "broken_install":', 1)[1]
    branch = branch.split('elif _firebase_down_reason == "transient":', 1)[0]
    assert "_fail(" in branch and "_warn(" not in branch


def test_the_reason_reaches_the_app_as_well():
    """The health endpoint publishes `downReason` verbatim, so the web app can
    tell a broken install from an outage without a new field."""
    src = code_only_deep(research.run_server)
    assert '"downReason": _firebase_down_reason,' in src
