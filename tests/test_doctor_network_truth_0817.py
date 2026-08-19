"""--doctor told a DNS-blocked owner their token was revoked.

⛔⛔ THE CIRCLE A REAL NEW OWNER WALKED, 2026-08-17. Their machine could not
resolve firestore.googleapis.com. They ran `--doctor`, which reported

    ✗  Firestore init failed · OS keystore empty or refresh token revoked
       → Run `python research.py --pair`

Every word of that is wrong for their situation, and the instruction is worse
than useless: re-pairing cannot fix a network, and it spends the pairing they
still had.

⭐⭐ `init_firebase` HAS ALWAYS KNOWN THE DIFFERENCE. It sets the reason
authoritatively — a raised exception from the live token refresh means network,
a `None` return means revoked — and it has done since #717. Doctor simply never
asked. This is the same shape as the four e2e items before it: a decision that
was already made, and a consumer reading something else.

⛔ AND EVERY REMEDY IN THAT NEIGHBOURHOOD COULD NOT RUN. Four messages said
`pip install -r requirements.txt`; a pipx install has no such file and never
has. The supervisor's abort was the worst — it built the path under the LOG
directory, which exists on no machine of either kind — and it is the line
printed at the exact moment the product stops working.
"""
import inspect
import re

import pytest

import research


# ── the remedy matches how this copy was installed ───────────────────────────

def test_a_source_checkout_gets_the_requirements_file(monkeypatch):
    monkeypatch.setattr(research, "_is_source_checkout", lambda: True)
    assert research._remedy_reinstall() == "pip install -r requirements.txt"


def test_an_installed_copy_gets_pipx(monkeypatch):
    monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
    got = research._remedy_reinstall()
    assert "requirements.txt" not in got, (
        "an installed copy has no requirements.txt and never has had one"
    )
    assert got == "pipx install --force superresearch"


def test_the_installed_remedy_forces(monkeypatch):
    """⭐ pipx treats re-installing a present package as a no-op AND exits 0, so
    a plain install would report success while changing nothing."""
    monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
    assert "--force" in research._remedy_reinstall()


def test_no_message_hardcodes_a_requirements_path_any_more():
    """⭐ THE CLASS GUARD. Any new message that prescribes requirements.txt
    directly is wrong for every installed owner."""
    src = inspect.getsource(research)
    remedy = inspect.getsource(research._remedy_reinstall)
    outside = src.replace(remedy, "")
    offenders = []
    for i, line in enumerate(outside.splitlines(), 1):
        if "requirements.txt" not in line:
            continue
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("*"):
            continue          # history and commentary are allowed to name it
        offenders.append(stripped)
    assert not offenders, (
        "these still prescribe requirements.txt without asking how this copy "
        f"was installed: {offenders}"
    )


def test_no_message_hands_a_posix_only_shell_line_to_the_reader():
    """The commonest new-owner platform is Windows; `source .venv/bin/activate`
    is not a thing there."""
    src = inspect.getsource(research)
    assert "source .venv/bin/activate" not in src


def test_the_supervisor_abort_prescribes_something_that_can_run():
    src = inspect.getsource(research)
    abort = src[src.index("SUPERVISOR ABORT:") - 400:]
    abort = abort[:abort.index("Missing: ") + 40]
    assert "_remedy_reinstall()" in abort
    assert "_log_dir / \"requirements.txt\"" not in abort


def test_the_supervisor_abort_says_what_it_means_for_the_machine():
    src = inspect.getsource(research)
    i = src.index("SUPERVISOR ABORT:")
    assert "cannot start" in src[i:i + 300], (
        "an abort has to say the machine will not run, not only what failed"
    )


# ── doctor asks the question it already had the answer to ────────────────────

def _code_only(text: str) -> str:
    """Drop comment lines. Every assertion below is about what the CLI PRINTS,
    and a comment explaining the old wording is not the old wording."""
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))


# The three branches, sliced on INDENTATION rather than on the first `else:`.
# The network branch now contains nested else clauses of its own, and a naive
# `.index("else:")` walked straight into one — a slice that silently measured
# the wrong code, which is the same failure mode as a stale mutation anchor.
_NET_HEAD = '    elif _firebase_down_reason == "transient":'
_REV_HEAD = '    else:\n        _fail("Firestore init failed"'


def _doctor_firestore_block() -> str:
    src = _code_only(inspect.getsource(research.run_doctor))
    return src[src.index("Checking Firestore connectivity"):]


def _network_branch() -> str:
    block = _doctor_firestore_block()
    return block[block.index(_NET_HEAD):block.index(_REV_HEAD)]


def _revoked_branch() -> str:
    block = _doctor_firestore_block()
    tail = block[block.index(_REV_HEAD):]
    return tail[:tail.index("\n    print()")]


def test_doctor_reads_the_authoritative_classification():
    block = _doctor_firestore_block()
    assert '_firebase_down_reason == "transient"' in block, (
        "init_firebase decides network-vs-revoke; doctor must ask it"
    )


def test_a_network_failure_no_longer_reads_as_a_revoked_token():
    net = _network_branch()
    assert "revoked" not in net
    assert "FIRESTORE_HOST" in net
    assert "nothing here needs re-pairing" in net, (
        "the reader's first instinct is to re-pair; say plainly that it cannot help"
    )


def test_a_network_failure_suggests_a_network_check_not_a_re_pair():
    net = _network_branch()
    assert "--pair" not in net, "re-pairing spends a working pairing to fix nothing"
    for cause in ("VPN", "proxy", "firewall", "DNS"):
        assert cause in net, f"{cause} not named"


def test_a_genuine_revoke_still_says_re_pair():
    """⛔ OVER-CORRECTION GUARD. The revoked case is real and its advice was
    always right — widening the network branch over it would strand the owner
    who actually did trigger a reset."""
    revoked = _revoked_branch()
    assert "OS keystore empty or refresh token revoked" in revoked
    assert "--pair" in revoked


def test_the_two_branches_cannot_both_fire():
    block = _doctor_firestore_block()
    assert block.count("elif _firebase_down_reason") == 1
    assert block.index(_NET_HEAD) < block.index(_REV_HEAD)


def test_the_patchright_failure_stops_asking_the_reader_a_question():
    """`venv mismatch?` was the entire detail — a question mark where the
    diagnosis belongs, on a probe that runs the SAME interpreter."""
    src = _code_only(inspect.getsource(research.run_doctor))
    assert "venv mismatch?" not in src
    assert "same interpreter" in src
    assert "partial or broken install" in src


# ── the QR line during pairing ───────────────────────────────────────────────

def test_the_missing_qr_library_is_not_reported_as_a_warning():
    """The pair code is printed as text either way, so nothing is lost and there
    is nothing for the reader to do. It was a WARN, mid-branded-screen, with a
    remedy that cannot run."""
    src = inspect.getsource(research)
    i = src.index("QR image skipped")
    tail = src[i:i + 400]
    assert '"INFO"' in tail
    assert "type the code below instead" in tail
    assert "requirements.txt" not in tail
