"""Wave 5: the doctor's network triage, against sockets that really fail.

⛔⛔ THE GAP THIS CLOSES. Every one of the five verdicts in
`test_network_triage_0817.py` is pinned with a hand-written probe dict, and the
only live run of `_probe_host` this product has ever had was on a WORKING
network. `google_blocked` and `blocked_after_dns` — the two the whole triage
exists for — had never executed against a real resolution or a real refusal.

⭐ SO EVERY PROBE HERE IS A REAL SOCKET, and no internet is required for any of
them:
    connects   — a listener this test binds on the loopback interface
    refused    — a loopback port this test binds and then closes, so the
                 kernel really answers ECONNREFUSED
    no DNS     — a name under `.invalid`, which RFC 2606 reserves precisely so
                 that it can never resolve

⚠ AND BE HONEST ABOUT WHAT IS STILL SYNTHETIC. The resolution failures, the
refusals and the connections are real; the HOSTNAMES are stand-ins, mapped onto
the google/control roles through the same table production reads. What this
still cannot reach is a machine whose whole resolver is down — that one needs a
person to unplug something, and it is the one remaining item on this fix.

Run: pytest tests/test_network_triage_live_0822.py -v
"""
from __future__ import annotations

import os
import socket
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
#  three real network outcomes
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def listening_port():
    """A loopback port with something really listening on it."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    yield s.getsockname()[1]
    s.close()


@pytest.fixture
def refusing_port():
    """A loopback port with nothing on it — bound to claim it, then closed, so
    the kernel answers a real ECONNREFUSED rather than a timeout."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _unresolvable() -> str:
    """A name that cannot resolve anywhere. `.invalid` is reserved by RFC 2606
    for exactly this; the uuid keeps a cached negative answer from a previous
    run out of it."""
    return f"sr-{uuid.uuid4().hex}.invalid"


# ══════════════════════════════════════════════════════════════════════════
#  1. the probe, against sockets rather than a fixture
# ══════════════════════════════════════════════════════════════════════════

class TestTheProbeAgainstRealSockets:

    def test_a_host_that_answers_reads_resolved_and_connected(self, listening_port):
        got = research._probe_host("127.0.0.1", port=listening_port, timeout=2.0)
        assert got["resolved"] is True
        assert got["connected"] is True
        assert got["addr"] == "127.0.0.1"
        assert got["resolve_error"] == ""
        assert got["connect_error"] == ""

    def test_a_refused_connection_resolves_but_does_not_connect(self, refusing_port):
        """⭐ THE SHAPE THE TRIAGE CALLS `blocked_after_dns`, produced by a real
        kernel refusal for the first time."""
        got = research._probe_host("127.0.0.1", port=refusing_port, timeout=2.0)
        assert got["resolved"] is True, "the name resolved — that half must hold"
        assert got["connected"] is False
        assert got["addr"] == "127.0.0.1"
        assert got["connect_error"], "a refusal with no reason recorded is useless"
        assert got["resolve_error"] == "", (
            "a refusal must not be reported as a resolution failure — they have "
            "different causes and different fixes")

    def test_a_name_that_cannot_resolve_reports_the_lookup_failure(self):
        """⭐ A REAL NXDOMAIN. The two facts stay separate: nothing resolved, so
        nothing was even attempted at the socket layer."""
        got = research._probe_host(_unresolvable(), port=443, timeout=2.0)
        assert got["resolved"] is False
        assert got["connected"] is False
        assert got["addr"] == ""
        assert got["resolve_error"], "the lookup failure was not recorded"
        assert got["connect_error"] == "", (
            "a name that never resolved cannot also have failed to connect")

    def test_the_probe_never_raises_whatever_the_network_does(self):
        """It is called in a loop inside a diagnostic. A raise there ends the
        one command a stuck person was told to run."""
        for host, port in ((_unresolvable(), 443), ("127.0.0.1", 1),
                           ("", 443), ("256.256.256.256", 443)):
            got = research._probe_host(host, port=port, timeout=1.0)
            assert set(got) == {"host", "resolved", "connected", "addr",
                                "resolve_error", "connect_error"}

    def test_a_failure_is_named_by_its_exception_type(self):
        """A bare message cannot be told apart from another; the type is what
        makes a support bundle worth reading.

        ⚠ MY FIRST VERSION OF THIS ASSERTED THE TYPE ENDS IN "Error". A real
        lookup failure on this platform is `socket.gaierror`, which does not —
        the test premise was wrong, not the code. What is actually worth holding
        is that the recorded string carries a type NAME and a message, both
        non-empty and separated."""
        got = research._probe_host(_unresolvable(), port=443, timeout=2.0)
        head, sep, rest = got["resolve_error"].partition(": ")
        assert sep, f"no type name recorded: {got['resolve_error']!r}"
        assert head and " " not in head, f"{head!r} is not an exception type"
        assert rest.strip(), "the type was recorded with no message behind it"


# ══════════════════════════════════════════════════════════════════════════
#  2. the five verdicts, off real probes
# ══════════════════════════════════════════════════════════════════════════

G1, G2, CTRL = "google-a.test", "google-b.test", "control.test"


@pytest.fixture
def roles(monkeypatch):
    """Put stand-in hosts into the same table production classifies by, so the
    verdict is reached the way it is reached in the field."""
    monkeypatch.setattr(research, "_DOCTOR_NET_TARGETS", (
        (G1, "the channel your machine and the web app talk over", "google"),
        (G2, "the sign-in refresh your machine needs", "google"),
        (CTRL, "a non-Google host the pipeline also needs", "control"),
    ))


def _as(host, probe):
    """A real probe result, re-labelled with the role host it stands in for.

    ⛔ Only the NAME is substituted. `resolved`, `connected`, `addr` and both
    error strings are whatever the sockets actually did."""
    out = dict(probe)
    out["host"] = host
    return out


class TestTheVerdictsOffRealSockets:

    def test_everything_answering_is_ok(self, roles, listening_port):
        live = research._probe_host("127.0.0.1", port=listening_port, timeout=2.0)
        verdict = research._network_verdict(
            [_as(G1, live), _as(G2, live), _as(CTRL, live)])
        assert verdict["kind"] == "ok"
        assert verdict["actions"] == []
        assert verdict["blocked_addrs"] == []

    def test_nothing_resolving_is_no_dns(self, roles):
        dead = research._probe_host(_unresolvable(), port=443, timeout=2.0)
        verdict = research._network_verdict(
            [_as(G1, dead), _as(G2, dead), _as(CTRL, dead)])
        assert verdict["kind"] == "no_dns"
        assert verdict["actions"], "a verdict with no next step is not a verdict"

    def test_only_google_failing_to_resolve_is_google_blocked(
            self, roles, listening_port):
        """⭐⭐ THE NEW OWNER'S EXACT SHAPE, and the first time it has been
        reached from a real lookup failure beside a real connection."""
        dead = research._probe_host(_unresolvable(), port=443, timeout=2.0)
        live = research._probe_host("127.0.0.1", port=listening_port, timeout=2.0)
        verdict = research._network_verdict(
            [_as(G1, dead), _as(G2, dead), _as(CTRL, live)])
        assert verdict["kind"] == "google_blocked"

    def test_resolving_but_refused_is_blocked_after_dns(
            self, roles, refusing_port):
        """⭐⭐ A real ECONNREFUSED, which is the outcome a firewall produces."""
        refused = research._probe_host("127.0.0.1", port=refusing_port, timeout=2.0)
        verdict = research._network_verdict(
            [_as(G1, refused), _as(G2, refused), _as(CTRL, refused)])
        assert verdict["kind"] == "blocked_after_dns"

    def test_the_refusing_address_is_reported_for_an_it_ticket(
            self, roles, refusing_port):
        """⛔ The address is the one thing a corporate firewall request has to
        name, and it comes from the probe rather than from a literal."""
        refused = research._probe_host("127.0.0.1", port=refusing_port, timeout=2.0)
        verdict = research._network_verdict(
            [_as(G1, refused), _as(G2, refused), _as(CTRL, refused)])
        assert "127.0.0.1" in verdict["blocked_addrs"]

    def test_one_host_refusing_among_resolvable_ones_is_still_a_firewall(
            self, roles, listening_port, refusing_port):
        """⚠ I ASSERTED `partial` HERE FIRST AND THE CODE WAS RIGHT, NOT ME.
        Every name resolved, so DNS is not in question at all; one refusal among
        them is still a refusal. `partial` is reserved for a set where BOTH kinds
        of failure appear — the test below."""
        live = research._probe_host("127.0.0.1", port=listening_port, timeout=2.0)
        refused = research._probe_host("127.0.0.1", port=refusing_port, timeout=2.0)
        verdict = research._network_verdict(
            [_as(G1, live), _as(G2, refused), _as(CTRL, live)])
        assert verdict["kind"] == "blocked_after_dns"
        assert verdict["headline"]
        assert "127.0.0.1" in verdict["blocked_addrs"]

    def test_a_lookup_failure_beside_a_refusal_is_not_called_a_firewall(
            self, roles, refusing_port, listening_port):
        """⛔ FOUND BY MUTATION. My first version of the test above asserted only
        that the verdict was not `ok`, which three different wrong answers
        satisfy. A name that did not resolve is a DNS fault; reporting it as a
        refused connection sends someone to their firewall over their resolver."""
        dead = research._probe_host(_unresolvable(), port=443, timeout=2.0)
        refused = research._probe_host("127.0.0.1", port=refusing_port, timeout=2.0)
        live = research._probe_host("127.0.0.1", port=listening_port, timeout=2.0)
        verdict = research._network_verdict(
            [_as(G1, dead), _as(G2, refused), _as(CTRL, live)])
        assert verdict["kind"] != "blocked_after_dns", (
            "one of these hosts never resolved — that is not 'DNS is fine'")
        assert verdict["kind"] != "no_dns", (
            "another host resolved and connected — resolution is not gone")
        assert verdict["kind"] == "partial"

    def test_the_mixed_verdict_still_reports_the_refusing_address(
            self, roles, refusing_port, listening_port):
        dead = research._probe_host(_unresolvable(), port=443, timeout=2.0)
        refused = research._probe_host("127.0.0.1", port=refusing_port, timeout=2.0)
        live = research._probe_host("127.0.0.1", port=listening_port, timeout=2.0)
        verdict = research._network_verdict(
            [_as(G1, dead), _as(G2, refused), _as(CTRL, live)])
        assert "127.0.0.1" in verdict["blocked_addrs"]

    def test_a_verdict_that_blames_the_network_always_says_what_to_do(
            self, roles, refusing_port, listening_port):
        """⭐ The founding complaint was a diagnosis with no next step."""
        refused = research._probe_host("127.0.0.1", port=refusing_port, timeout=2.0)
        live = research._probe_host("127.0.0.1", port=listening_port, timeout=2.0)
        dead = research._probe_host(_unresolvable(), port=443, timeout=2.0)
        # ⛔ THE MIXED SET WAS MISSING and it is the one that falls through every
        # named branch to the last return — so `partial` could ship with an empty
        # action list and nothing here would notice.
        for probes in ([_as(G1, refused), _as(G2, refused), _as(CTRL, refused)],
                       [_as(G1, refused), _as(G2, refused), _as(CTRL, live)],
                       [_as(G1, dead), _as(G2, refused), _as(CTRL, live)],
                       [_as(G1, dead), _as(G2, dead), _as(CTRL, live)],
                       [_as(G1, dead), _as(G2, dead), _as(CTRL, dead)]):
            verdict = research._network_verdict(probes)
            assert verdict["kind"] != "ok"
            assert verdict["actions"], f"{verdict['kind']} hands over nothing to do"


# ══════════════════════════════════════════════════════════════════════════
#  3. what the real target set does on THIS machine
# ══════════════════════════════════════════════════════════════════════════

def test_the_shipped_targets_all_resolve_from_a_working_network():
    """⚠ NOT a health check on Google — it is a check on OUR list. A hostname
    that has been renamed or misspelled would make the doctor report a blocked
    network on every machine on earth, and nothing else would catch it.

    Skipped rather than failed when this machine has no network: the suite must
    stay green on a plane."""
    hosts = [t[0] for t in research._DOCTOR_NET_TARGETS]
    results = {h: research._probe_host(h, timeout=4.0) for h in hosts}
    if not any(r["resolved"] for r in results.values()):
        pytest.skip("this machine has no name resolution at all")
    unresolved = [h for h, r in results.items() if not r["resolved"]]
    assert not unresolved, (
        f"{unresolved} did not resolve while other hosts did — either these "
        f"names are wrong, or this network blocks them")
