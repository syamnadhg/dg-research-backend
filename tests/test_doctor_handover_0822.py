"""Wave 4: the doctor's hand-over line stops being a network-fault feature.

⛔⛔ IT LIVED INSIDE ONE BRANCH. `_doctor_share_logs_line()` — "Still stuck? Run
`--send-logs`… No terminal? Use Report Bug" — was printed only under
`elif _firebase_down_reason == "transient"`. Every other fault this command
reports ends the page with nothing to do next: patchright not importable,
Chromium refusing to launch, the supervisor unit missing, the refresh token
revoked, `--serve` not running, DISPLAY not reaching the user unit. The owner's
ask (2026-08-17) was that *every* failure a person can be left holding should
point at the way to hand it over.

⭐ AND `✓ Healthy` IS THE CASE A PERSON IS MOST STUCK IN. They ran the doctor
because something is wrong and the answer was that nothing here is — which is
precisely when the logs are the next move. The line opens "Still stuck?", a
question only that reader is being asked.

⚠ SOURCE-PINNED, AND THAT IS A REAL LIMIT WORTH STATING. `run_doctor` probes
Firestore, imports patchright and launches Chromium in a subprocess with a 60s
timeout; there is no cheap way to execute it here. So these tests pin the call
site's POSITION — unconditional, at function level, after the summary — which is
the property that makes it print on every run, and they pin that the branch it
used to live in no longer prints it. Mutation confirms the pins can feel both.

Run: pytest tests/test_doctor_handover_0822.py -v
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from conftest import code_only_deep  # noqa: E402


CALL = 'print(f"  {_c(_DIM, _doctor_share_logs_line())}")'


def _doctor() -> str:
    return code_only_deep(research.run_doctor)


def test_the_doctor_ends_every_run_with_the_hand_over():
    """⛔ FOUR SPACES. The indentation IS the assertion: at function level the
    line is unconditional, and one level deeper it is back inside whichever
    branch happened to enclose it."""
    src = _doctor()
    assert f"\n    {CALL}\n" in src, (
        "the hand-over is not printed unconditionally at the end of a doctor run")


def test_the_hand_over_is_printed_once_and_not_per_fault():
    """⛔ Two authors of one sentence is how `--resurrect` came to be prescribed
    twice in a three-step list — the defect `_dedupe_actions` exists for.

    ⭐ TWO SITES, NOT ONE, SINCE 2026-08-24 — and they cannot both run. Cross-
    verification found the unsupported-platform branch RETURNING before the
    closing line, so the one reader who can be told least else reached the end
    of the page with no next step, under a commit that said the hand-over
    "closes every doctor run". That branch is an early return, so a run reaches
    exactly one of the two. The count is pinned at two rather than relaxed, so
    a THIRD copy — the per-fault repetition this test exists to prevent —
    still fails.
    """
    assert _doctor().count("_doctor_share_logs_line()") == 2


def test_the_second_site_is_the_unsupported_branch_and_it_RETURNS():
    """⭐ What makes two copies safe is that the first one exits. If that
    `return` were ever dropped, the branch would fall through to the second and
    print the hand-over twice on one page — the exact defect above."""
    src = _doctor()
    branch = src[src.index('if plat == "Unsupported"'):]
    branch = branch[:branch.index('_ok(f"Platform:')]
    assert "_doctor_share_logs_line()" in branch, (
        "the unsupported-platform branch returns without the hand-over")
    assert "\n        return" in branch, (
        "the unsupported branch no longer returns, so both copies now print")


def test_the_network_branch_no_longer_carries_its_own_copy():
    """The branch it used to live in must not print it a second time now that
    every run ends with it."""
    src = _doctor()
    net = src[src.index('elif _firebase_down_reason == "transient":'):]
    net = net[:net.index('    else:\n        _fail("Firestore init failed"')]
    assert "_probe_host(" in net, "the slice missed the network branch entirely"
    assert "_doctor_share_logs_line()" not in net, (
        "the network fault now gets the hand-over twice on one page")


def test_the_hand_over_comes_after_the_verdict_not_before_it():
    """It answers "what now", so it has to follow both the healthy verdict and
    the issue count — not sit in the middle of the checks."""
    src = _doctor()
    # ⭐ The LAST occurrence: the first belongs to the unsupported-platform
    # early return, which never reaches a verdict at all.
    end = src.rindex(CALL)
    assert end > src.index("'✓  Healthy.'")
    assert end > src.index("Manual steps still required")


def test_a_healthy_machine_is_offered_it_too():
    """⭐ THE HALF THAT IS EASY TO DROP. `issues_found == 0` prints one line and
    used to end there. The call sits AFTER the whole if/else, so both verdicts
    reach it — pinned by slicing from the healthy branch and finding the call
    outside the `else` that follows it."""
    src = _doctor()
    healthy = src.index("if issues_found == 0:")
    assert src.rindex(CALL) > healthy
    # …and not inside the else, which is where "only when something is wrong"
    # would put it.
    else_block = src[src.index("        tm.tm_emit(tm.Ev.DOCTOR_RUN"):src.rindex(CALL)]
    assert "_doctor_share_logs_line" not in else_block


def test_the_line_itself_still_names_both_routes():
    """Re-pinned here because this wave widened WHO sees it — if the sentence
    ever loses the command or the no-terminal route, it is now wrong on every
    page rather than on one."""
    line = research._doctor_share_logs_line()
    assert "--send-logs" in line
    assert "Report Bug" in line
    assert 'add_argument("--send-logs"' in inspect.getsource(research), (
        "the line names a command that no longer exists")


# ══ wave 10.10: the Linux page names each fix once ═════════════════════
#
# ⛔⛔ EXECUTED, NOT READ — the one doctor test in this file that runs the
# doctor. Every probe it makes is faked at its seam (the platform, the
# subprocess calls, the process list, the port), so the page is the real
# `run_doctor` printing a real summary.
#
# WHAT WAS WRONG: on Linux, a supervisor unit missing DISPLAY added the
# `--resurrect` remedy WITH a hint glued on, and `--serve not running` added the
# plain one. `_dedupe_actions` compares whole strings, so both survived and the
# summary told the reader to run `--resurrect` twice.

def _linux_doctor(tmp_path, monkeypatch, capsys, *, unit_has_display, serving):
    import contextlib
    import subprocess
    import types

    unit = tmp_path / "dgresearch-supervisor.service"
    unit.write_text("[Service]\n" + ("Environment=DISPLAY=:0\n" if unit_has_display else ""),
                    encoding="utf-8")

    def _run(argv, **_kw):
        cmd = " ".join(str(a) for a in argv)
        out = ""
        if "sync_playwright" in cmd:
            out = "OK"
        elif "is-active" in cmd:
            out = "active"
        elif "show-environment" in cmd:
            out = "DISPLAY=:0\n"
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(research, "_supervisor_platform", lambda: "Linux")
    monkeypatch.setattr(research, "load_paired_uid", lambda: "uid-1")
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-1")
    monkeypatch.setattr(research, "_sync_spinner_ctx",
                        lambda *a, **k: contextlib.nullcontext())
    monkeypatch.setattr(research, "init_firebase", lambda: True)
    monkeypatch.setattr(research, "_SUPERVISOR_UNIT_PATH", unit)
    monkeypatch.setattr(research, "_check_linger_status", lambda: "yes")
    monkeypatch.setattr(research, "_installed_supervisor_path", lambda: "")
    monkeypatch.setattr(research, "_supervisor_path_value", lambda: "")
    monkeypatch.setattr(research, "_search_path_findings",
                        lambda **kw: {"rows": [], "actions": []})
    monkeypatch.setattr(research, "_enumerate_research_py_procs",
                        lambda: [(4242, "research.py --serve", "serve")] if serving else [])
    monkeypatch.setattr(research, "_supervisor_evidence",
                        lambda **kw: {"lines": [], "legacy": False})
    monkeypatch.setattr(research, "_port_holders", lambda port: [])
    monkeypatch.setattr(research.tm, "tm_emit", lambda *a, **k: None)
    monkeypatch.setattr(research, "_detect_supervised", lambda: False)
    capsys.readouterr()
    research.run_doctor()
    page = capsys.readouterr().out
    assert "Manual steps still required" in page, page[-1500:]
    steps = page[page.index("Manual steps still required"):]
    return page, [ln for ln in steps.splitlines() if "--resurrect" in ln]


def test_a_linux_page_names_resurrect_once_when_both_findings_ask_for_it(
        tmp_path, monkeypatch, capsys):
    """⛔⛔ THE DEFECT: both findings on one page, one remedy in the list."""
    page, resurrects = _linux_doctor(tmp_path, monkeypatch, capsys,
                                     unit_has_display=False, serving=False)
    assert "Unit missing Environment=DISPLAY" in page
    assert "--serve not running" in page
    assert len(resurrects) == 1, f"--resurrect listed {len(resurrects)} times: {resurrects}"


def test_the_graphical_session_hint_moved_into_the_warning(tmp_path, monkeypatch,
                                                            capsys):
    """⭐ The hint was worth keeping; it now rides the finding that needs it,
    not the remedy that two findings share."""
    page, resurrects = _linux_doctor(tmp_path, monkeypatch, capsys,
                                     unit_has_display=False, serving=True)
    warn = next(ln for ln in page.splitlines() if "Unit missing Environment=DISPLAY" in ln)
    assert "graphical-session terminal" in warn
    assert len(resurrects) == 1 and "graphical-session" not in resurrects[0]
