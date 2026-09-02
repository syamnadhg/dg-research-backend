"""Stretch 7 — the platform-locked hints, the dead doctor row, and the refusal
that said nothing.

Three defects, measured 2026-09-02, all of the same family: code that is correct
on exactly one platform, or on exactly one path, and silent everywhere else.

⛔⛔ THE TRACKER NAMED ONE HALF OF A SYMMETRIC PAIR AND THE WRONG VICTIM. Its box
was "research.py prints a platform-locked `lsof` command, and a green test pins
it" — true, and Windows-only. The mirror it never mentioned is worse: the
doctor's Port-8000 check RAN `ss` under `if plat in ("Linux", "Darwin")`, and
`ss` does not exist on Darwin. The FileNotFoundError went into a bare
`except Exception: pass`, so on the platform most runs happen on the row printed
NEITHER pass nor fail — a dead check that reads as a clean run. Windows was
excluded from the row altogether by the same gate.
"""
from __future__ import annotations

import importlib
import inspect

import pytest

research = importlib.import_module("research")
from conftest import code_only  # noqa: E402


# ── the hint helper, per platform ────────────────────────────────────────────

@pytest.mark.parametrize(
    "platform,must_have,must_not_have",
    [
        ("win32", "netstat", ("lsof", "ss -")),
        ("darwin", "lsof", ("ss -", "netstat")),
        ("linux", "ss -ltnp", ("lsof", "netstat")),
    ],
)
def test_the_port_hint_names_a_tool_that_exists_there(
        monkeypatch, platform, must_have, must_not_have):
    """⛔ Both directions on purpose. Asserting the right tool is present cannot
    see a hint that names ALL THREE tools — which would be "correct" on every
    platform and useless on each."""
    monkeypatch.setattr(research.sys, "platform", platform)
    hint = research._port_holder_hint(8000)
    assert must_have in hint, (platform, hint)
    for wrong in must_not_have:
        assert wrong not in hint, (platform, wrong, hint)


def test_the_port_hint_carries_the_port_it_was_asked_about(monkeypatch):
    """A hint for the wrong port sends somebody looking at the wrong socket. The
    refusal it feeds is about a specific worker port, not always 8000."""
    for platform in ("win32", "darwin", "linux"):
        monkeypatch.setattr(research.sys, "platform", platform)
        assert "9911" in research._port_holder_hint(9911), platform


# ── the consumers, because a helper nobody calls is not a fix ────────────────

def test_the_stuck_port_refusal_uses_the_helper():
    """⛔⛔ HELPER PINNED, CONSUMER NOT — the exact failure this project keeps
    hitting. The tests above would all pass with the refusal still printing a
    hardcoded `lsof`, which is the defect."""
    src = code_only(research.run_server)
    assert "_port_holder_hint(port)" in src, (
        "the stuck-port refusal stopped using the platform-aware hint")
    assert "lsof" not in src, (
        "a hardcoded lsof came back into run_server — on Windows that is the one "
        "line meant to unblock them, and it cannot run")
    assert "ss -ltnp" not in src


def _doctor_port_block() -> str:
    """The Port-8000 region of run_doctor, COMMENTS STRIPPED.

    ⛔⛔ `code_only` is not optional here and the first draft proved it: the
    not-platform-gated assertion matched `plat in ("Linux", "Darwin")` inside
    the explanatory comment that was added ABOVE the fix to record the old gate.
    A presence assertion cannot tell code from prose about code."""
    src = code_only(research.run_doctor)
    start = src.index("_holders_8000 = _port_holders(8000)")
    # Back up to the enclosing try, forward to the next section's real code.
    start = src.rindex("try:", 0, start)
    return src[start:src.index('plat == "Linux"', start)]


def test_the_doctor_asks_the_cross_platform_lookup_not_one_tool():
    block = _doctor_port_block()
    assert "_port_holders(8000)" in block, (
        "the doctor shells out for the port again — that is how the macOS row "
        "died into an `except Exception: pass`")
    assert '"ss"' not in block and "'ss'" not in block, block
    assert "_sp.run(" not in block, "the doctor runs a port tool directly again"


def test_the_doctor_row_is_not_platform_gated_any_more():
    """⛔ Windows never got this row at all. The old gate was
    `if plat in ("Linux", "Darwin")`, so the one platform whose port-reclaim path
    the code itself calls hardest was the one told nothing."""
    block = _doctor_port_block()
    assert 'plat in ("Linux", "Darwin")' not in block, (
        "the platform gate is back — Windows loses the row silently")


OURS = {"pid": 11, "name": "python", "ours": True}
THEIRS = {"pid": 22, "name": "nginx", "ours": False}


@pytest.mark.parametrize("holders,verdict,who", [
    ([], "unbound", None),
    ([OURS], "ours", OURS),
    ([THEIRS], "squatter", THEIRS),
])
def test_the_port_verdict_has_three_distinct_outcomes(holders, verdict, who):
    """⛔⛔ BEHAVIOURAL, BECAUSE THE SOURCE PINS THAT REPLACED THIS COULD NOT SEE
    THEIR MUTANTS. One asserted `h.get("ours")` was in the block and was
    satisfied by the branch BODY while the condition was gone; the other
    asserted "not bound" was present and was satisfied by a literal in a branch
    made unreachable. Both survived mutation, which is how they were found.

    Three outcomes because a person acts differently on each: ours is fine,
    somebody else's needs killing, nothing bound means the API is down for a
    different reason entirely."""
    got_verdict, got_who = research._port_row_verdict(holders)
    assert got_verdict == verdict
    assert got_who == who


def test_our_serve_is_found_even_when_a_squatter_is_listed_first():
    """Order independence, and it matters: the remedy for a squatter is to kill
    the binding, which is the opposite of what to do about our own --serve."""
    assert research._port_row_verdict([THEIRS, OURS]) == ("ours", OURS)


def test_the_squatter_reported_is_one_of_the_holders():
    """Not a fabricated row — the PID printed is one somebody can act on."""
    verdict, who = research._port_row_verdict([THEIRS, {"pid": 33, "ours": False}])
    assert verdict == "squatter" and who["pid"] == 22


def test_the_doctor_asks_the_verdict_rather_than_deciding_inline():
    """The consumer pin. A perfect verdict function the doctor does not call is
    not a fix — this project has hit that nine times."""
    block = _doctor_port_block()
    assert "_port_row_verdict(_holders_8000)" in block, (
        "the doctor decides the port row inline again")
    assert 'h.get("ours")' not in block, (
        "the doctor is inspecting holders itself again — that is the second copy")
    assert "not bound" in block and "non-Super-Research" in block, (
        "a rewrite collapsed two of the three sentences")
    assert "_port_holder_hint(8000)" in block, (
        "the remedy line stopped being platform-aware")


def test_the_doctor_says_so_when_it_could_not_look():
    """⛔⛔ THE ORIGINAL FAILURE MODE, AND THE ONE WORTH NOT REPEATING: the check
    threw and printed nothing, so a dead check read as a clean run. If the lookup
    itself fails the row must still appear."""
    block = _doctor_port_block()
    assert "Port 8000 unknown" in block, (
        "a failed lookup is silent again — that is the bug, restated")
    assert "except Exception" in block and "pass\n" not in block.split("except Exception")[1][:80], (
        "the failure is swallowed rather than reported")


# ── the three helpers this one joins, which had no tests at all ─────────────
#
# ⛔ MEASURED: `_kill_pid_hint`, `_process_manager_label` and
# `_supervisor_artifact_label` have existed since 2026-05-20 under a comment
# describing exactly this class of bug, and a grep for all three names across the
# root suite returned ZERO hits. A mutation flipping any of their branches was a
# free survivor. The new helper joins a pattern that was itself unguarded.

@pytest.mark.parametrize("platform,expected", [
    ("win32", "taskkill /F /PID 42"),
    ("darwin", "kill -9 42"),
    ("linux", "kill -9 42"),
])
def test_the_kill_hint_is_platform_correct(monkeypatch, platform, expected):
    monkeypatch.setattr(research.sys, "platform", platform)
    assert research._kill_pid_hint(42) == expected


@pytest.mark.parametrize("platform,needle,forbidden", [
    ("win32", "Task Manager", "Activity Monitor"),
    ("darwin", "Activity Monitor", "Task Manager"),
    ("linux", "shell", "Task Manager"),
])
def test_the_process_manager_label_is_platform_correct(
        monkeypatch, platform, needle, forbidden):
    monkeypatch.setattr(research.sys, "platform", platform)
    label = research._process_manager_label()
    assert needle in label and forbidden not in label, (platform, label)


@pytest.mark.parametrize("platform,expected", [
    ("win32", "Scheduled Task"),
    ("darwin", "LaunchAgent"),
    ("linux", "systemd-user unit"),
])
def test_the_supervisor_artifact_label_is_platform_correct(
        monkeypatch, platform, expected):
    monkeypatch.setattr(research.sys, "platform", platform)
    assert research._supervisor_artifact_label() == expected


# ── the update refusal that said nothing ────────────────────────────────────

class _Boom:
    def collection(self, *_a, **_k):
        return self

    def document(self, *_a, **_k):
        return self

    def get(self):
        raise RuntimeError("firestore is having a day")


def test_a_device_read_failure_tells_the_person_instead_of_going_quiet(monkeypatch):
    """⛔⛔ THE ONE REFUSAL ON THIS HANDLER THAT WROTE NO STATUS. The invariant is
    stated in the handler's own comment eight lines above it — "a refused command
    writes an updateStatus too" — and every other branch honours it. This one
    returned bare, so the app sat on "started" until its own timeout and then
    reported a WAIT rather than a REASON.

    ⭐ merge=True matters and is asserted: a refusal reports on the request, and
    must not be able to lower `needsRestart` or wipe `latest`. That clobber was
    already found once on the restart branch."""
    calls = []
    monkeypatch.setattr(research, "_firebase_db", _Boom())
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.13")
    monkeypatch.setattr(
        research, "_write_update_status",
        lambda device_id, status, **kw: calls.append((device_id, status, kw)) or True)

    research._handle_update_command({"submittedBy": "u1"}, "dev-1", None)

    assert calls, "the device-read failure still refuses in silence"
    device_id, status, kw = calls[0]
    assert device_id == "dev-1"
    assert status["state"] == "failed"
    assert kw.get("merge") is True, (
        "a refusal must merge — it reports on the request and cannot be allowed "
        "to clobber needsRestart or latest")
    reason = status.get("reason", "")
    assert reason, "failed with no reason is the wait-not-a-reason bug again"
    assert "read" in reason.lower(), reason
    # Plain words, not a class name or a traceback.
    assert "RuntimeError" not in reason and "Exception" not in reason, reason


def test_that_refusal_still_reports_the_running_version(monkeypatch):
    """`current` is what the app shows beside the failure; without it the panel
    has a reason and no version to attach it to."""
    calls = []
    monkeypatch.setattr(research, "_firebase_db", _Boom())
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.13")
    monkeypatch.setattr(
        research, "_write_update_status",
        lambda device_id, status, **kw: calls.append(status) or True)
    research._handle_update_command({"submittedBy": "u1"}, "dev-1", None)
    assert calls[0].get("current") == "0.1.13"
