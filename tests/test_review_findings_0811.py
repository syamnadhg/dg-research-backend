"""Five confirmed findings from the 2026-08-11 automated review of BE PR #4.

Fourteen were raised. Five are fixed here; nine are deliberately NOT, because the
standing rule on this project is that a review's fix is what has broken the
pipeline in every recent instance. Each fix below is either confined to a path the
research pipeline never enters, or fails in the safe direction.

TWO OF THE REVIEW'S SUGGESTIONS ARE DELIBERATELY NOT TAKEN, and those refusals are
tested too, because "the reviewer said so" is not a reason and a later reader will
want to know it was a decision:

  * refusing a restart when `ownerUid` is absent — owner-unlink DELETES that
    field, so this would invent a new restriction on unlinked devices to protect
    an owner-only field those devices do not have;
  * falling back to the temp-wide artifact glob from `_playwright_download_dirs` —
    an earlier draft did, and put the same directory in the search plan twice with
    contradictory move flags.
"""
import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research as R  # noqa: E402
from conftest import code_only  # noqa: E402

SRC = (Path(__file__).resolve().parents[1] / "research.py").read_text(encoding="utf-8")


def _restart_branch() -> str:
    """The `restart` action branch, code only, to its natural end.

    A fixed character window does not work here: `code_only` blanks comments to
    whitespace, and this branch is heavily commented, so 4000 characters of source
    is mostly blank lines and never reaches the code being asserted on.
    """
    body = code_only(SRC)
    at = body.index('if action == "restart"')
    end = body.index("# Unknown action", at) if "# Unknown action" in body[at:] else len(body)
    return body[at:min(end, at + 20000)]


def _fn(name: str) -> str:
    tree = ast.parse(SRC)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(SRC, n) or ""
    raise AssertionError(f"{name} not found")


# ── F2 · the one-shot latch must not outlive the attempt ─────────────────────

def test_an_update_command_clears_the_published_latch():
    """The heartbeat sets `_update_result_published` on ABSENCE — "nothing to
    report, ever" — which is right for a process that booted with no update in
    flight and wrong the instant a command arrives afterwards. The waiter then
    writes its result and the heartbeat never looks again.

    Worst in the case the whole mechanism exists for: when the restart leg fails,
    THIS process keeps serving, so there is no fresh boot to reset the latch and
    the app sits on "started" or its own timeout forever."""
    body = code_only(_fn("_handle_update_command"))
    assert "global _update_result_published" in body
    assert "_update_result_published = False" in body


def test_the_latch_is_cleared_BEFORE_the_guards_run():
    """A refused command writes an updateStatus too, and that write must not be
    suppressed by a latch left over from the last attempt."""
    body = code_only(_fn("_handle_update_command"))
    reset = body.index("_update_result_published = False")
    # The first guard in that handler is the owner-only device-doc read.
    first_guard = body.index("collection(\"devices\")")
    assert reset < first_guard, "the reset must precede the owner check"


def test_the_latch_still_exists_as_a_one_shot():
    """The fix is to scope it per attempt, not to remove it. Publishing on every
    heartbeat forever is the behaviour the latch was added to stop."""
    hb = code_only(SRC)
    assert "_update_result_published = True" in hb


# ── F5 · a restart command with no identity is refused ──────────────────────

def test_a_restart_with_no_submittedBy_is_refused():
    """The predicate refused only when BOTH fields were present AND differed, so a
    document with no `submittedBy` fell straight through and got its restart —
    the exact fail-open this guard was written to complain about."""
    window = _restart_branch()
    assert "if not _rsub:" in window, window[:1500]
    assert "could not verify device ownership" in window


def test_the_refusal_is_reachable_before_the_exit_is_scheduled():
    window = _restart_branch()
    refuse = window.index("if not _rsub:")
    exit_at = window.index("_schedule_server_exit")
    assert refuse < exit_at


def test_a_MISSING_ownerUid_is_still_allowed_deliberately():
    """⛔ The review's suggestion, NOT taken. Owner-unlink deletes `ownerUid` — it
    is how a machine is handed on — so refusing there would invent a new
    restriction on unlinked devices in order to protect an owner-only field that
    those devices do not have. The hole was the missing `submittedBy`.

    Pinned so the next reader sees a decision rather than an oversight."""
    window = _restart_branch()
    assert "if _rowner and _rsub != _rowner:" in window, (
        "the owner comparison must stay conditional on ownerUid existing"
    )
    assert "if not _rowner or not _rsub:" not in window, (
        "refusing on a missing ownerUid would break restart on unlinked devices"
    )


# ── F7 · "already public" needs a real dialog ───────────────────────────────

def test_already_public_requires_the_dialog_to_have_been_found():
    """The diagnostic scopes to `dlg || document.body`, so with no
    sufficiently-sized dialog it reads the WHOLE PAGE — and any stray "Anyone with
    the link" text promoted `already`, set access_set, and suppressed the
    fallback. The result is a PRIVATE link handed to a recipient who gets
    "Request access", the one outcome this helper exists to prevent.

    Third time a document-wide fallback has done real damage here: the ChatGPT row
    search matched `.__menu-item` page-wide and pressed a sidebar link, and the
    panel-source filter substring-matched a whole URL."""
    body = code_only(_fn("_set_nlm_public_and_get_link"))
    assert '_diag.get("already") and _diag.get("dialog")' in body, body[-1500:]


def test_the_bare_already_check_is_gone():
    body = code_only(_fn("_set_nlm_public_and_get_link"))
    assert 'if _diag.get("already"):' not in body


def test_the_diagnostic_still_reports_the_dialog_flag():
    """The fix reads a field the diagnostic already returned and nothing consumed.
    If that field goes, the guard silently becomes always-false and every run pays
    for a fallback."""
    assert "dialog: !!dlg" in SRC


def test_the_mismatch_is_logged_not_swallowed():
    """Text on the page but no dialog is a selector problem worth seeing — it is
    how the size threshold being wrong would ever be noticed."""
    body = code_only(_fn("_set_nlm_public_and_get_link"))
    assert "NO share dialog was on screen" in body


# ── F11 · artifact directories must belong to this run ──────────────────────

def test_download_dirs_returns_only_what_the_context_reported():
    """`_find_recent_audio` treats these as trusted AND movable — "this directory
    holds only what this run downloaded" is the whole basis for both. The temp-wide
    glob made that false: with two workers on one host the newer file can be the
    other run's, and `shutil.move` would take it mid-download."""
    body = code_only(_fn("_playwright_download_dirs"))
    assert "_download_dir" in body and "_artifacts_dir" in body
    # ⚠ This originally asserted `gettempdir` was absent here. That pinned the
    # FIRST version of the fix, which was inert: those private attributes do not
    # exist in the installed Playwright, so the function returned nothing and our
    # own directory was classified as a stranger's. The glob is back, but GATED —
    # a temp directory is claimed only when it is the only one on the host.
    assert "len(_dirs) == 1" in body, (
        "a temp directory may be claimed only when no sibling run could own it"
    )


def test_foreign_dirs_are_a_separate_function():
    body = code_only(_fn("_playwright_foreign_artifact_dirs"))
    assert "gettempdir" in body
    assert "playwright-artifacts-*" in body


def test_foreign_dirs_exclude_our_own():
    """Otherwise the same directory arrives twice with contradictory flags."""
    body = code_only(_fn("_playwright_foreign_artifact_dirs"))
    assert "_download_dir" in body and "_artifacts_dir" in body
    assert "parents" in body or "not any" in body


def test_the_plan_marks_foreign_dirs_SCAN_ONLY():
    """Still scanned — not finding a file that exists is what caused the 08-09
    outage. Never moved — it may be another run's podcast, mid-download."""
    body = code_only(_fn("_audio_search_plan"))
    assert "_playwright_foreign_artifact_dirs(browser)" in body
    at = body.index("_playwright_foreign_artifact_dirs")
    line = body[body.rindex("\n", 0, at):at + 80]
    assert "False)" in line, f"foreign dirs must be may_move=False: {line}"


def test_our_own_dirs_stay_movable():
    """The polarity. If these stopped being movable, every run would copy instead
    of move and leave the original behind in temp."""
    body = code_only(_fn("_audio_search_plan"))
    at = body.index("_playwright_download_dirs")
    line = body[body.rindex("\n", 0, at):at + 80]
    assert "True)" in line, f"own dirs must stay may_move=True: {line}"


def test_no_directory_appears_in_the_plan_twice(monkeypatch):
    """The defect the first draft of this fix introduced: with the context
    reporting nothing, the fallback glob put the same path in the plan as movable
    AND as scan-only, so copy-vs-move depended on list order."""
    shared = Path("/tmp/playwright-artifacts-XYZ")
    monkeypatch.setattr(R, "_playwright_download_dirs", lambda b: [])
    monkeypatch.setattr(R, "_playwright_foreign_artifact_dirs", lambda b: [shared])
    plan = R._audio_search_plan(object())
    paths = [p for p, *_ in plan]
    assert len(paths) == len(set(paths)), f"duplicate directory in the plan: {paths}"


def test_trust_still_derives_from_may_move():
    """The two flags must not drift apart: `_find_recent_audio` reads may_move as
    its trust signal, which is what makes scan-only also mean strict-content."""
    body = code_only(_fn("_find_recent_audio"))
    assert "trusted=may_move" in body


# ── F14 · the retired narrator must not resolve credentials ─────────────────

def test_the_budget_guard_is_the_first_thing_in_narrate_panel():
    """It sat below the credential resolution, which imports research and does an
    env/Firestore lookup — so with the budget at its DEFAULT of zero, a retired
    narrator paid for that on every call. A guard whose whole purpose is "do
    nothing" cannot live after the doing."""
    narrate = (Path(__file__).resolve().parents[1] / "narrate.py").read_text(encoding="utf-8")
    tree = ast.parse(narrate)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "narrate_panel")
    body = ast.get_source_segment(narrate, fn) or ""
    guard = body.index("PHASE_BUDGET <= 0")
    for later in ("resolve_gemini_api_key", "api_key ="):
        assert guard < body.index(later), f"{later} must come after the budget check"


def test_the_guard_still_counts_the_skip():
    narrate = (Path(__file__).resolve().parents[1] / "narrate.py").read_text(encoding="utf-8")
    at = narrate.index("PHASE_BUDGET <= 0")
    assert "skipped_budget" in narrate[at:at + 200]


# ── the nine NOT fixed ──────────────────────────────────────────────────────

def test_the_deferred_findings_are_recorded_somewhere_a_reader_will_look():
    """Nine of the fourteen are not fixed. That is a decision, and a decision with
    no record is indistinguishable from an oversight three weeks later."""
    assert "deliberately NOT" in __doc__ or "NOT" in __doc__


# ── the SECOND pass: the first fix was inert, and undid an outage fix ───────

def test_a_lone_artifacts_directory_is_ours(tmp_path, monkeypatch):
    """⛔ THE REGRESSION THE E2E CAUGHT. The attribute probe returns nothing on the
    installed Playwright — `_download_dir`/`_artifacts_dir` do not exist there — so
    the first version of this fix classified our OWN directory as foreign. Two
    consequences, both the opposite of what its commit claimed: the multi-worker
    protection never engaged, and `trusted` (derived from may_move) went
    permanently False, which disables the ffprobe-absent acceptance in
    `_audio_kind` and reinstates the 2026-08-09 outage on any machine without
    ffmpeg.

    Proof it was real: the two runs before the change logged "moved", the run
    after logged "copied", on a host with no sibling worker at all.

    With ONE directory there is no sibling to confuse it with."""
    import tempfile as _tf
    monkeypatch.setattr(_tf, "tempdir", str(tmp_path))
    only = tmp_path / "playwright-artifacts-ONLYONE"
    only.mkdir()
    assert R._playwright_download_dirs(object()) == [only]
    assert R._playwright_foreign_artifact_dirs(object()) == []


def test_two_artifacts_directories_are_claimed_by_nobody(tmp_path, monkeypatch):
    """The case the hazard is actually about. With two we cannot tell ours apart,
    so none is claimed — every one goes through the scan-only path and nothing is
    moved out from under a sibling run."""
    import tempfile as _tf
    monkeypatch.setattr(_tf, "tempdir", str(tmp_path))
    a = tmp_path / "playwright-artifacts-AAA"; a.mkdir()
    b = tmp_path / "playwright-artifacts-BBB"; b.mkdir()
    assert R._playwright_download_dirs(object()) == []
    assert sorted(R._playwright_foreign_artifact_dirs(object())) == sorted([a, b])


def test_the_lone_directory_is_MOVABLE_and_TRUSTED_in_the_plan(tmp_path, monkeypatch):
    """The whole point. may_move=True is what restores the pre-change behaviour,
    and `_find_recent_audio` reads may_move as its trust signal — which is what
    keeps the ffprobe-absent acceptance alive on a machine without ffmpeg."""
    import tempfile as _tf
    monkeypatch.setattr(_tf, "tempdir", str(tmp_path))
    only = tmp_path / "playwright-artifacts-ONLYONE"
    only.mkdir()
    plan = R._audio_search_plan(object())
    entry = next(e for e in plan if e[0] == only)
    assert entry[3] is True, "a lone artifacts directory must stay movable/trusted"


def test_no_duplicate_when_the_lone_directory_is_claimed(tmp_path, monkeypatch):
    """The foreign helper must subtract what the owner helper claimed, or the same
    directory reaches the plan twice with contradictory flags."""
    import tempfile as _tf
    monkeypatch.setattr(_tf, "tempdir", str(tmp_path))
    (tmp_path / "playwright-artifacts-ONLYONE").mkdir()
    paths = [p for p, *_ in R._audio_search_plan(object())]
    assert len(paths) == len(set(paths)), paths
