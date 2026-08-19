"""The doctor localizes the network fault instead of listing suspects.

⛔ The owner's ask, verbatim: *"shouldn't we fix the doctor stuff as well, so the
doctor tells them the RIGHT solution"* — and, separately, *"even if the pair
doesn't go through, show the send logs command so the user would know he can
share the logs on failure to the dev team and get it sorted."*

⭐⭐ IT CANNOT FIX A NETWORK, AND MUST NOT PRETEND TO. Resolvers, VPN clients,
proxies and firewall rules are the user's own machine and network, most need
administrator rights, and none are ours to change. What a diagnostic CAN do is
stop handing over four suspects and say WHICH ONE — and where it cannot, hand
over the log.

⭐ The three hosts are the product's own dependencies, so the control costs
nothing extra and its answer is directly relevant. It is what separates "this
machine has no working DNS at all" from "this network answers for everything
EXCEPT Google's APIs" — the corporate-resolver case, and the most likely cause
of the outage that started all of this.
"""
import inspect

import pytest

import research


FS = "firestore.googleapis.com"
ST = "securetoken.googleapis.com"
AN = "api.anthropic.com"


def _p(host, resolved, connected, addr="", rerr="", cerr=""):
    return {"host": host, "resolved": resolved, "connected": connected,
            "addr": addr, "resolve_error": rerr, "connect_error": cerr}


def _kind(probes):
    return research._network_verdict(probes)["kind"]


# ── the target set ───────────────────────────────────────────────────────────

def test_the_targets_are_the_products_own_dependencies():
    hosts = [t[0] for t in research._DOCTOR_NET_TARGETS]
    assert research.FIRESTORE_HOST in hosts
    assert ST in hosts, "the host whose failure the new owner actually hit"
    assert any(t[2] == "control" for t in research._DOCTOR_NET_TARGETS), (
        "without a non-Google control there is no way to tell 'DNS is broken' "
        "from 'this network blocks Google'"
    )


def test_there_is_exactly_one_control():
    kinds = [t[2] for t in research._DOCTOR_NET_TARGETS]
    assert kinds.count("control") == 1
    assert kinds.count("google") >= 2


def test_the_control_is_not_a_google_host():
    control = next(t[0] for t in research._DOCTOR_NET_TARGETS if t[2] == "control")
    assert "google" not in control, (
        "a Google host cannot be the control for Google being blocked"
    )


# ── the five verdicts ────────────────────────────────────────────────────────

def test_a_healthy_path_says_so():
    assert _kind([_p(FS, 1, 1, "1.1.1.1"), _p(ST, 1, 1, "1.1.1.2"),
                  _p(AN, 1, 1, "2.2.2.2")]) == "ok"


def test_nothing_resolves_is_no_dns():
    assert _kind([_p(FS, 0, 0, rerr="gaierror: x"), _p(ST, 0, 0, rerr="gaierror: x"),
                  _p(AN, 0, 0, rerr="gaierror: x")]) == "no_dns"


def test_the_new_owners_exact_shape_is_google_blocked():
    """⭐ His log said `address lookup failed for firestore.googleapis.com`
    while the machine was otherwise on a working network."""
    assert _kind([_p(FS, 0, 0, rerr="gaierror: DNS query cancelled"),
                  _p(ST, 0, 0, rerr="gaierror: DNS query cancelled"),
                  _p(AN, 1, 1, "2.2.2.2")]) == "google_blocked"


def test_resolving_but_not_connecting_is_a_firewall_not_dns():
    assert _kind([_p(FS, 1, 0, "1.1.1.1", cerr="TimeoutError"),
                  _p(ST, 1, 0, "1.1.1.2", cerr="TimeoutError"),
                  _p(AN, 1, 0, "2.2.2.2", cerr="TimeoutError")]) == "blocked_after_dns"


def test_a_mixed_result_is_not_forced_into_a_confident_answer():
    """⛔ OVER-CORRECTION GUARD. A split-tunnel VPN produces a mix, and claiming
    one confident cause there would be a new wrong answer replacing the old one."""
    assert _kind([_p(FS, 0, 0, rerr="gaierror: x"), _p(ST, 1, 1, "1.1.1.2"),
                  _p(AN, 1, 1, "2.2.2.2")]) == "partial"


@pytest.mark.parametrize("junk", [None, [], [1, 2, "x"], [{}]])
def test_junk_never_raises_and_never_claims_ok(junk):
    v = research._network_verdict(junk)
    assert isinstance(v, dict)
    assert v["kind"] != "ok", "an absent measurement is not a clean bill of health"


# ── what each verdict tells the reader to do ─────────────────────────────────

def _v(probes):
    return research._network_verdict(probes)


def test_every_fault_carries_at_least_one_action():
    for probes in (
        [_p(FS, 0, 0, rerr="x"), _p(ST, 0, 0, rerr="x"), _p(AN, 0, 0, rerr="x")],
        [_p(FS, 0, 0, rerr="x"), _p(ST, 0, 0, rerr="x"), _p(AN, 1, 1, "2.2.2.2")],
        [_p(FS, 1, 0, "1.1.1.1", cerr="x"), _p(ST, 1, 0, "1.1.1.2", cerr="x"),
         _p(AN, 1, 0, "2.2.2.2", cerr="x")],
        [_p(FS, 0, 0, rerr="x"), _p(ST, 1, 1, "1.1.1.2"), _p(AN, 1, 1, "2.2.2.2")],
    ):
        assert _v(probes)["actions"], f"{_v(probes)['kind']} leaves the reader nothing to do"


def test_a_healthy_path_gives_no_actions():
    """⛔ OVER-CORRECTION GUARD. Advice on a working network is noise, and noise
    is how the next real message gets skipped."""
    assert _v([_p(FS, 1, 1, "1.1.1.1"), _p(ST, 1, 1, "1.1.1.2"),
               _p(AN, 1, 1, "2.2.2.2")])["actions"] == []


def test_every_fault_names_the_vpn_because_disconnecting_it_settles_the_question():
    for probes in (
        [_p(FS, 0, 0, rerr="x"), _p(ST, 0, 0, rerr="x"), _p(AN, 0, 0, rerr="x")],
        [_p(FS, 0, 0, rerr="x"), _p(ST, 0, 0, rerr="x"), _p(AN, 1, 1, "2.2.2.2")],
        [_p(FS, 1, 0, "1.1.1.1", cerr="x"), _p(ST, 1, 0, "1.1.1.2", cerr="x"),
         _p(AN, 1, 0, "2.2.2.2", cerr="x")],
    ):
        assert "VPN" in " ".join(_v(probes)["actions"])


def test_the_google_blocked_case_gives_a_sentence_for_someone_elses_it_team():
    """Most owners cannot change a corporate resolver. They can forward one
    sentence to whoever can."""
    v = _v([_p(FS, 0, 0, rerr="x"), _p(ST, 0, 0, rerr="x"), _p(AN, 1, 1, "2.2.2.2")])
    blob = " ".join(v["actions"])
    assert "administers" in blob
    assert "googleapis.com" in blob


def test_a_firewall_verdict_hands_over_the_addresses_it_ticket_needs():
    v = _v([_p(FS, 1, 0, "142.250.1.1", cerr="x"), _p(ST, 1, 0, "142.250.1.2", cerr="x"),
            _p(AN, 1, 1, "2.2.2.2")])
    assert v["blocked_addrs"] == ["142.250.1.1", "142.250.1.2"]
    assert "443" in " ".join(v["actions"])


def test_a_dns_verdict_lists_no_addresses_because_there_are_none():
    v = _v([_p(FS, 0, 0, rerr="x"), _p(ST, 0, 0, rerr="x"), _p(AN, 0, 0, rerr="x")])
    assert v["blocked_addrs"] == []


def test_the_captive_portal_case_is_named_in_the_no_dns_advice():
    """Hotel and campus networks resolve nothing until you accept their terms,
    and that is indistinguishable from a broken resolver without being told."""
    blob = " ".join(_v([_p(FS, 0, 0, rerr="x"), _p(ST, 0, 0, rerr="x"),
                        _p(AN, 0, 0, rerr="x")])["actions"]).lower()
    assert "hotel" in blob or "campus" in blob


# ── the probe asks two questions, not one ────────────────────────────────────

def test_the_probe_reports_resolution_and_connection_separately():
    src = inspect.getsource(research._probe_host)
    assert "getaddrinfo" in src and "create_connection" in src
    assert "resolve_error" in src and "connect_error" in src


def test_a_failed_resolution_short_circuits_the_connect():
    """You cannot connect to a name you could not look up, and trying would add
    a second timeout to every already-slow diagnosis."""
    src = inspect.getsource(research._probe_host)
    head = src[:src.index("create_connection")]
    assert "return out" in head


def test_the_probe_survives_a_hostname_that_cannot_resolve():
    got = research._probe_host("this-name-does-not-exist.superresearch-probe.invalid")
    assert got["resolved"] is False
    assert got["resolve_error"], "a failure with no reason is the defect being fixed"
    assert got["connected"] is False


def test_the_probe_is_bounded():
    src = inspect.getsource(research._probe_host)
    assert "timeout" in src, "an unbounded probe turns a diagnosis into a hang"


# ── the doctor runs it, and only when it is relevant ─────────────────────────

def test_the_triage_only_runs_on_the_network_branch():
    """⛔ A healthy machine must not pay for six network calls to be told it is
    healthy."""
    src = inspect.getsource(research.run_doctor)
    net = src[src.index('elif _firebase_down_reason == "transient":'):]
    net = net[:net.index('    else:\n        _fail("Firestore init failed"')]
    assert "_probe_host(" in net
    healthy = src[src.index("Checking Firestore connectivity"):
                  src.index('elif _firebase_down_reason == "transient":')]
    assert "_probe_host(" not in healthy


def test_the_doctor_says_plainly_that_this_is_not_ours_to_change():
    """⭐ A diagnostic that implies it will fix a VPN is the same species of lie
    as the message that told them to re-pair."""
    src = inspect.getsource(research.run_doctor)
    assert "cannot change any of this for you" in src
    assert "Nothing is wrong with your install or your pairing" in src


def test_the_doctor_feeds_its_verdict_into_the_manual_steps():
    src = inspect.getsource(research.run_doctor)
    assert 'manual_actions.extend(_verdict["actions"]' in src


# ── the hand-over line ───────────────────────────────────────────────────────

def test_the_share_logs_line_names_the_real_file():
    """⭐ Read from the live state dir at CALL time, not baked in at import — the
    suite relocates that dir, and this test only passes because the path follows
    it. A hardcoded home path would have looked identical here and been wrong on
    any machine whose state dir had moved."""
    line = research._doctor_share_logs_line()
    assert line.count("backend.log") == 1
    assert str(research._STATE_DIR) in line
    assert str(research._STATE_DIR / "logs" / "backend.log") in line


def test_the_share_logs_line_names_the_command_and_the_command_exists():
    """⛔⛔ THE WHOLE WAVE IN ONE ASSERTION, and it has now flipped exactly once.

    Until 2026-08-18 this asserted the OPPOSITE: that the line did NOT name a
    `--send-logs` command, because the command did not exist and naming it would
    have been the very defect wave 1 spent itself removing. Wave 2 shipped the
    command, so the assertion inverted in the same commit — which is what it was
    written to do.

    ⭐ The pairing survives in both directions: the line may name the command
    only while the command is really there. If `--send-logs` is ever removed,
    this fails rather than leaving a promise behind.
    """
    line = research._doctor_share_logs_line()
    src = inspect.getsource(research)
    named = "--send-logs" in line
    exists = 'add_argument("--send-logs"' in src
    assert exists, "the command is gone — take it out of the hand-over line too"
    assert named, (
        "the command exists but the hand-over line does not mention it, which is "
        "the whole point of the line"
    )
    assert callable(getattr(research, "cmd_send_logs", None))


def test_the_share_logs_line_names_a_second_route_for_someone_with_no_shell():
    assert "Report Bug" in research._doctor_share_logs_line()


# ── every pairing failure hands over a way out ───────────────────────────────

@pytest.mark.parametrize("marker", [
    "no answer within the pairing window",
    "could not reach the pairing service",
    "pairing stopped on an error we have no specific advice for",
])
def test_each_pairing_failure_ends_with_the_hand_over(marker):
    src = inspect.getsource(research)
    i = src.index(marker)
    tail = src[i:i + 900]
    assert "_doctor_share_logs_line()" in tail, (
        f"{marker!r} leaves the reader holding a failure with no way to hand it on"
    )


def test_the_pair_timeout_no_longer_gives_one_answer_to_two_questions():
    """⛔ `re-run --pair to start fresh` was the same advice whether nobody typed
    the code or this machine could not reach us. It fixes the first and is pure
    theatre for the second."""
    src = inspect.getsource(research)
    assert "polling timed out — re-run --pair to start fresh" not in src
    i = src.index("no answer within the pairing window")
    block = src[i:i + 900]
    assert "never entered" in block
    assert "could not reach us" in block
    assert "--doctor" in block


def test_the_pair_timeout_says_nothing_was_left_half_paired():
    """The reader's real fear is a half-created device they now have to clean up."""
    src = inspect.getsource(research)
    i = src.index("no answer within the pairing window")
    assert "nothing was left half-paired" in src[i:i + 300]


def test_the_pairing_catchall_admits_it_has_no_specific_advice():
    """⭐ The one branch that by definition cannot diagnose itself should say so
    rather than print a raw exception and stop."""
    src = inspect.getsource(research)
    assert "unexpected error: {e}" not in src
    i = src.index("pairing stopped on an error we have no specific advice for")
    assert "is safe" in src[i:i + 500], "say whether re-running is safe"


def test_the_outage_notice_points_at_the_thing_that_can_localize_it():
    lines = research._firestore_outage_notice(
        down_for=600, attempts=12, last_spoken_ago=None)
    blob = " ".join(lines)
    assert "--doctor" in blob
    assert "backend.log" in blob
