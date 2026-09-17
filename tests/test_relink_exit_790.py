"""7.9-0 — what a relink recovery does when nothing is going to restart it.

⛔⛔ THE INCIDENT, MEASURED 2026-09-06. The owner reset their pair code on a
machine that deliberately has no supervisor and was not running. Recovery lives
only inside a running serve, so nothing recovered for hours and the computer
silently left the public list. When they finally ran serve, the relink watcher
recovered in one second — new refresh token, listing flag set, deletion timer
cancelled — and then called `os._exit(0)` on the assumption that a supervisor
would respawn it "within ~5s". There was none. Exit code 0, so the shell showed
no error. It read as a crash, and the machine stayed unlisted.

⭐⭐ THE ANSWER ALREADY EXISTED ONE SCREEN AWAY. `_recover_after_reconnect` makes
the identical exit-or-stay decision and asks `_supervisor_is_my_parent()`, whose
docstring names this exact foreground setup. The relink path never got it. These
tests read the source of the branch, because the alternative is driving a
watcher that ends its own process.

⛔ THE EXIT ITSELF IS CORRECT AND IS NOT UNDER TEST HERE. An in-process swap
leaves listeners bound to a revoked gRPC channel, delivering nothing, silently.
A fresh process is the right answer; the defect was assuming somebody else would
provide one.
"""
import ast
import inspect
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402


def _code_only(text: str) -> str:
    """Comments and docstrings out; every other string literal kept.

    ⛔ The comments in this branch quote what it used to do, so a raw substring
    search matches the explanation instead of the code."""
    doc_lines = set()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            doc_lines.update(
                range(first.lineno, (first.end_lineno or first.lineno) + 1)
            )
    return "\n".join(
        l for i, l in enumerate(text.splitlines(), 1)
        if i not in doc_lines and not l.strip().startswith("#")
    )


SRC = _code_only(
    inspect.getsource(research._revoked_recovery_loop)  # noqa: SLF001
)
#: ⛔ STRIPPED, because the seam's docstring quotes `os.execv` while explaining
#: why the call is not inline any more — and a guard that matches its own
#: explanation is measuring prose.
SEAM = _code_only(inspect.getsource(research._relink_reexec))  # noqa: SLF001


def test_the_exit_asks_whether_anything_will_restart_it():
    """⛔⛔ THE WHOLE DEFECT IN ONE ASSERTION. Without this question the branch
    ends the owner's only process and tells them nothing."""
    assert "_supervisor_is_my_parent()" in SRC


def test_the_supervised_path_still_exits():
    """⛔ THE OVER-CORRECTION GUARD. Where a supervisor exists the exit is
    cheap, deterministic and already correct — removing it would trade a real
    defect for a subtler one, listeners bound to a dead channel.

    ⛔ SCOPED TO THE BRANCH. The first version asserted `_os._exit(0)` appeared
    anywhere in this function, which the wall-clock give-up branch also
    satisfies — so it would have passed with the supervised exit deleted
    outright. Cross-verify caught it."""
    branch = SRC[SRC.index("if _supervisor_is_my_parent():"):]
    branch = branch[:branch.index("if _os.environ.get(")]
    assert "_os._exit(0)" in branch, (
        "the supervised branch must still exit, and this must read THAT exit"
    )


def test_the_unsupervised_path_restarts_itself():
    assert "_relink_reexec()" in SRC


def test_the_restart_is_behind_a_seam_and_not_inline():
    """⛔⛔ THE FIRST VERSION OF THIS WAVE CALLED `os.execv` INLINE HERE, and
    `test_revoked_recovery_loop_cap.py` drives this loop for real. That test
    carefully replaces `os._exit` with a raising sentinel so it cannot kill the
    runner — and had nothing to replace for an inline exec. So driving the loop
    re-execed PYTEST, 71% through the suite, and the run ended with exit code 0
    and no summary: exactly the silence this wave exists to remove, reproduced
    by its own fix.
    ⭐ One function means one thing to replace, and it means no future edit to
    this loop can reach a process-ending call that a test cannot intercept."""
    assert "execv" not in SRC, "the exec must not be inline in the loop"
    assert callable(research._relink_reexec)  # noqa: SLF001
    seam = SEAM
    assert "os.execv" in seam


def test_the_seam_sets_the_marker_before_it_execs():
    """⛔ AFTER THE EXEC IS TOO LATE — there is no "after". The new process
    inherits the environment, so a marker set on the wrong side of that call
    would never be seen and the guard would never fire.

    ⛔ INDEXED OVER STRIPPED SOURCE. The first version of this test read the raw
    source and found `os.execv` in the seam's own DOCSTRING, which sits above
    the marker — so it failed on the explanation rather than the order. That is
    the third time this wave that a comment or docstring quoting the thing being
    searched for has broken a guard."""
    assert SEAM.index("RELINK_REEXEC_ENV") < SEAM.index("os.execv")


def test_the_seam_reports_failure_rather_than_raising():
    """⛔ AN EXEC THAT FAILED LEAVES THIS PROCESS ALIVE AND OWING THE PERSON A
    SENTENCE. Letting the exception out would land it in the loop's broad
    handler, which logs a generic line and sleeps — losing the one message that
    tells the owner what to do."""
    assert "except Exception" in SEAM
    assert "return False" in SEAM


def test_the_restart_cannot_loop():
    """⛔⛔ AN INVISIBLE RESTART LOOP IS WORSE THAN THE DEFECT IT REPLACES. The
    marker has to be an environment variable, not a module global, precisely
    because it must survive into a process that has not run this file yet."""
    assert "RELINK_REEXEC_ENV" in SRC
    assert research.RELINK_REEXEC_ENV.startswith("SR_")
    src_lines = SRC.splitlines()
    guard = [l for l in src_lines if "RELINK_REEXEC_ENV" in l and "environ.get" in l]
    assert guard, "the re-exec must be guarded by a read of the marker"
    setter = [l for l in SEAM.splitlines()
              if "RELINK_REEXEC_ENV" in l and "environ[" in l]
    assert setter, "the marker must be written, and the seam is where it lives"


def test_a_failed_restart_still_names_the_command():
    """⛔ AN EXEC THAT FAILED HAS NOT REPLACED THIS PROCESS. What follows the
    call must be the sentence, not a bare exit — otherwise the rarest path is
    the one that reproduces the original defect."""
    tail = SRC[SRC.index("_relink_reexec()"):]
    before_exit = tail[:tail.index("_os._exit(0)")]
    assert "log(" in before_exit
    assert "--serve" in before_exit or "_PROG" in before_exit


def test_the_last_word_names_the_command():
    """⭐ THE OWNER'S SHELL RETURNED TO A PROMPT WITH THE INSTRUCTION FORTY
    LINES ABOVE IT. If this process is going to end, the thing a person has to
    do next is the last thing it says."""
    # ⛔ SLICE THE BRANCH, NOT THE FUNCTION. The first version of this test
    # used the LAST `log(` in the whole watcher and measured the loop's generic
    # error handler thirty lines further down — a slice that silently reads the
    # wrong code, which is the same failure mode as a stale mutation anchor and
    # is called out as such elsewhere in this suite.
    after_exec = SRC[SRC.index("_relink_reexec()"):]
    final_block = after_exec[:after_exec.index("_os._exit(0)")]
    last_log = final_block[final_block.rindex("log("):]
    assert "--serve" in last_log and "_PROG" in last_log


def test_the_recovery_still_confirms_what_it_fixed():
    """⛔ THE TWO LINES THAT TOLD THE OWNER IT HAD WORKED must survive: without
    them the restart looks like the crash it used to be."""
    assert "pairConfirmedAt" in SRC


# ── the seam, driven ─────────────────────────────────────────────────────────
#
# ⛔⛔ EVERY TEST ABOVE READS SOURCE, AND CROSS-VERIFY CALLED THAT OUT: the part
# of this change most likely to be wrong was the part no test executed. These
# call the seam for real, with the one syscall replaced.

def test_the_seam_marks_before_it_calls_exec(monkeypatch):
    """⛔ AFTER THE EXEC THERE IS NO AFTER. The new process inherits the
    environment, so a marker written on the wrong side of that call is never
    seen and the once-only guard never fires."""
    seen = {}

    def fake_execv(path, argv):
        seen["marker"] = os.environ.get(research.RELINK_REEXEC_ENV)
        seen["argv"] = list(argv)
        raise OSError("blocked in test")

    monkeypatch.delenv(research.RELINK_REEXEC_ENV, raising=False)
    monkeypatch.setattr(os, "execv", fake_execv)
    assert research._relink_reexec() is False  # noqa: SLF001
    assert seen["marker"] == "1"


def test_the_seam_execs_a_command_that_can_actually_run(monkeypatch):
    """⛔⛔ `[sys.executable, *sys.argv]` IS NOT THIS PROGRAM'S COMMAND LINE on a
    pipx or pip install, where the entry point is a console script — and on
    Windows that script is an .exe the interpreter cannot be handed. The restart
    would have failed on exactly the installs most likely to be unsupervised.
    `sys.orig_argv` is the real command line, interpreter included."""
    seen = {}

    def fake_execv(path, argv):
        seen["path"] = path
        seen["argv"] = list(argv)
        raise OSError("blocked in test")

    monkeypatch.setattr(os, "execv", fake_execv)
    monkeypatch.setattr(sys, "orig_argv", ["/usr/bin/whatever", "--serve"])
    research._relink_reexec()  # noqa: SLF001
    assert seen["path"] == "/usr/bin/whatever"
    assert seen["argv"] == ["/usr/bin/whatever", "--serve"]
    assert seen["argv"][0] == seen["path"], "argv[0] must be the program itself"


def test_a_failed_exec_returns_rather_than_raising(monkeypatch):
    """⛔ THE PROCESS IS STILL ALIVE AND STILL OWES THE PERSON A SENTENCE.
    Letting the exception out lands it in the loop's broad handler, which logs a
    generic line and sleeps — losing the message that says what to do."""
    def boom(*_a, **_kw):
        raise OSError("nope")

    monkeypatch.setattr(os, "execv", boom)
    assert research._relink_reexec() is False  # noqa: SLF001


def test_a_healthy_boot_clears_the_marker(monkeypatch):
    """⛔⛔ IT WAS SET AND NEVER CLEARED, so the guard meant "once per process
    LINEAGE" — a machine that recovered from one reset would refuse to restart
    itself after the NEXT one, reproducing the incident months later with no
    clue why. A healthy boot cannot license a loop, because a looping process
    never reaches one."""
    monkeypatch.setenv(research.RELINK_REEXEC_ENV, "1")
    src = _code_only(inspect.getsource(research.init_firebase))
    assert "os.environ.pop(RELINK_REEXEC_ENV" in src
    tail = src[src.index("_firebase_db = client"):]
    assert "RELINK_REEXEC_ENV" in tail, (
        "the marker must be cleared only after the client is actually up"
    )


# ── the hour-long give-up ────────────────────────────────────────────────────
#
# ⛔⛔ THIS BRANCH SURVIVED THE WAVE'S FIRST PASS. It sits 120 lines from the
# sentence the wave removed, in the same function, and said the same thing:
# "Owner must run `--pair` to recover." Cross-verify found it; the mutation
# harness then proved there was no guard, because the mutant that put the
# sentence back survived a green suite.

def _giveup_branch() -> str:
    tail = SRC[SRC.index("MAX_RECOVERY_WALLCLOCK_SEC:"):]
    return tail[:tail.index("poll_secret = load_poll_secret()")]


def test_the_giveup_does_not_lead_with_pairing():
    """⛔ IT IS THE ONE PLACE PAIRING MIGHT BE RIGHT, WHICH IS WHY IT NEEDS CARE
    RATHER THAN THE SHARED REMEDY. An hour of failed redeems usually means the
    owner never approved and the record's own TTL deleted it — genuinely gone,
    and only pairing replaces it. But if they DID approve and the redeems failed
    for another reason, the record survived and pairing throws away a machine
    that is still there. This code cannot tell: it has no token left to look
    with. So it must not lead with the destructive answer.

    ⛔ RE-POINTED IN WAVE 9, AND STRICTLY STRONGER. It used to accept
    "look under Devices" as the first instruction, which is where the sentence
    then sent people: "use the code you were emailed". That was dead by
    construction — this branch only fires after MAX_RECOVERY_WALLCLOCK_SEC, an
    hour, while an emailed code's window is RESET_WINDOW_MINUTES = 15, so the
    code it offered had ALWAYS expired by the time the line printed. The old
    assertion could not see that, because looking-before-pairing was all it
    asked. It now also demands the real page name and the repair that survives
    the window, which is what the web and the agent both say."""
    branch = _giveup_branch()
    first = branch[:branch.index("--pair")] if "--pair" in branch else branch
    # ⛔ THE WHOLE CLAUSE, NOT "still listed". The retired sentence ALSO said
    # "computer is still listed", so a bare substring test for it would have
    # passed against the code this wave replaced — measuring nothing while
    # looking like the guard. Asked once: would it have passed an hour ago? It
    # would. So it reads the clause only the new sentence has.
    assert "open the app: if this computer is still listed" in first, (
        "the first instruction must be to look, not to pair"
    )
    assert "Settings → Manage devices" in first, (
        "Account → Manage devices is not a page; Reset lives under Settings"
    )
    assert "press Reset again" in first, (
        "past the 15-minute window a second Reset is the only door left, and "
        "this branch fires an hour in — so it must not offer the emailed code"
    )
    assert "use the code you were emailed" not in branch, (
        "an hour-old emailed code answers code_expired every time"
    )
    assert "--serve" in first


def test_the_giveup_says_what_pairing_would_cost():
    branch = _giveup_branch()
    assert "creates a new computer" in branch
    assert "only if it is GONE" in branch


def test_the_giveup_tells_an_unsupervised_machine_it_is_stopping():
    """⛔ THE ORIGINAL LEFT THE OWNER AT A PROMPT with an hour-old log and no
    last line — the same silence that made a successful recovery read as a
    crash."""
    branch = _giveup_branch()
    assert "_supervisor_is_my_parent()" in branch
    assert "stopping now" in branch


def test_the_giveup_still_exits():
    """⛔ THE OVER-CORRECTION. Restarting here would re-enter the same dead
    loop, which is the one thing this branch exists to stop."""
    assert "_os._exit(0)" in _giveup_branch()
    assert "_relink_reexec" not in _giveup_branch()
