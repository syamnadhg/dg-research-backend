"""7.9-0 — the --serve banner may not describe a machine that is not connected.

⛔⛔ MEASURED 2026-09-06, from the owner's own terminal. Their pair code reset had
revoked this machine's token, so the Firestore init printed an ERROR and returned
False. One second later the banner printed a green `(active)` device, a heartbeat
cadence, and "Listening for pipeline jobs. Keep this terminal open." Then the
recovery watcher exited the process. Every one of those lines was decided before
anybody asked whether the connection had worked:

  * `(active)` came from `load_device_id()` — a file on disk. It answers "has
    this machine ever been paired", which stays true through any outage.
  * the heartbeat row was a formatted constant, while the task that does the
    beating is only created when the client exists.
  * the footer announced a job listener that had been skipped on the same
    condition, and told the owner to keep open a terminal the process was about
    to close.

⭐ THE FIX IS NOT NEW INFORMATION. `init_firebase` had already resolved by the
time this strip prints and the client is a module global; the banner simply
never read it. These tests read the source, because the alternative is booting a
real server.
"""
import ast
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402


def _code_only(text: str) -> str:
    doc_lines = set()
    for node in ast.walk(ast.parse(text)):
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
        ln for i, ln in enumerate(text.splitlines(), 1)
        if i not in doc_lines and not ln.strip().startswith("#")
    )


SRC = _code_only(inspect.getsource(research.run_server))
STRIP = SRC[SRC.index("_ctx_rows_serve = ["):]


def test_the_banner_asks_whether_it_is_connected():
    """⛔ THE MISSING QUESTION. Everything else here follows from it."""
    assert "_connected = _firebase_db is not None" in SRC


def test_the_device_chip_is_not_decided_by_a_file_on_disk():
    """⛔⛔ `(active)` USED TO BE UNCONDITIONAL under `if _device_id_now:`, so it
    described a machine that had been paired once, not one that is working."""
    chip_block = SRC[SRC.index("_state_chip"):SRC.index("_ctx_rows_serve = [")]
    assert "_connected" in chip_block
    assert "(not connected)" in chip_block


def test_the_heartbeat_row_is_not_a_constant():
    """⛔ A cadence printed while nothing is beating is a claim about the
    machine, not a description of a setting."""
    hb = STRIP[STRIP.index('("Heartbeat"'):]
    hb = hb[:hb.index("]")]
    assert "_connected" in hb


def test_the_footer_does_not_announce_a_listener_that_was_skipped():
    footer = SRC[SRC.index("Listening for pipeline jobs"):]
    footer = footer[:footer.index("Ctrl+C")]
    assert "if _connected:" in SRC[:SRC.index("Listening for pipeline jobs")][-400:]
    assert "Not listening yet" in footer


def test_both_footers_say_to_keep_the_terminal_open():
    """⛔⛔ THE DISCONNECTED FOOTER DROPPED IT AND CROSS-VERIFY CAUGHT THAT.
    This is the boot where the instruction matters MOST: the relink watcher that
    recovers a reset machine lives inside THIS process, so closing the window is
    the one action that guarantees the computer never comes back. Removing the
    line because the machine is not listening confused two different reasons to
    stay open.

    ⛔ AND THE FIRST VERSION OF THIS TEST WOULD NOT HAVE NOTICED: it asserted
    the sentence appeared anywhere in the function, which the connected branch
    satisfies on its own — so it passed while the disconnected branch had
    dropped it. Both branches are read separately now."""
    footer = SRC[SRC.index("Listening for pipeline jobs"):]
    footer = footer[:footer.index("Ctrl+C")]
    connected, disconnected = footer.split("else:", 1)
    assert "Keep this terminal open" in connected
    assert "Keep this terminal open" in disconnected


def test_the_connected_and_disconnected_footers_cannot_both_print():
    """⛔ One `if`, one `else` — not two independent prints that could ever
    stack into a banner claiming both."""
    # ⛔ A COUNT OF `print(` IS THE WRONG PROPERTY and the first version of this
    # test used one — it counted four where it expected three, because a slice
    # that starts mid-line drops the very call it was counting. What has to hold
    # is not how many lines print; it is that the two footers are one `if` and
    # its `else`, so no boot can ever emit both.
    guard = SRC[:SRC.index("Listening for pipeline jobs")]
    assert guard.rstrip().endswith(":") or "if _connected:" in guard[-200:], (
        "the connected footer must sit under the connection check"
    )
    between = SRC[SRC.index("Listening for pipeline jobs"):
                  SRC.index("Not listening yet")]
    assert "else:" in between, (
        "the two footers must be one if/else, not two independent prints"
    )
    assert "if " not in between.replace("if _connected:", ""), (
        "nothing may re-open a condition between the two branches"
    )


def test_the_remedy_is_gated_on_the_credential_state_not_on_disk_fields():
    """⛔⛔ THE INCIDENT MACHINE HAD BOTH DISK FIELDS. Gating the remedy on
    `_device_id_now and _paired_uid_now` excluded the exact computer this wave
    came from — only its token was revoked — so it fell through to the next
    branch and was offered `--resurrect`, the one thing its owner had already
    refused, on a boot that could not work. Cross-verify caught it."""
    assert "_cred_now = credential_state_now()" in SRC
    assert "if _cred_now != CRED_HEALTHY:" in SRC
    assert "if not (_device_id_now and _paired_uid_now):" not in SRC


def test_the_banner_next_action_never_offers_pairing_to_a_paired_machine():
    """⛔⛔ A TENTH ADVICE SITE, missed by the wave's own sweep of eight, on the
    busiest surface in the program: the next-actions block hardcoded
    `--pair` for every unhealthy machine — including one that would lose its
    identity and its public listing by running it."""
    block = SRC[SRC.index("if _cred_now != CRED_HEALTHY:"):]
    block = block[:block.index("elif not _currently_supervised:")]
    assert "--pair" in block, "a never-paired machine still needs the offer"
    guard = block[block.index("--pair") - 300:block.index("--pair")]
    assert "CRED_NEVER_PAIRED" in guard and "CRED_ORPHANED" in guard, (
        "the pairing offer must be gated on the two states it is safe for"
    )
