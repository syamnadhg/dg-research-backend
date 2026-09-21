"""The Resume backstop for an abandoned run, pinned where it is PLUGGED IN.

⛔⛔ WHAT THIS FILE IS FOR. `tests/test_dead_worker_backstop_64.py` has fifteen
tests and they are good ones — but every one of them calls
`_read_dead_worker_ids`, `_write_worker_dead_marker` or
`_reconcile_dead_worker_runs` directly. The three lines that make any of it RUN
have no test at all: the supervisor's marker write, worker 1's `create_task`,
and the boot-time retraction. Delete any one and the suite stays green while
every orphaned run silently reverts to the 2026-07-16 behaviour the stale
KNOWN LIMITATION still describes — frozen "ongoing", no Resume, until somebody
repairs the worker by hand. Helper-pinned, consumer-not.

⛔⛔ AND THE MEASUREMENT GAP WAS HIDING A REAL ONE. The supervisor gives up on a
worker in FOUR places — the initial fleet spawn failing, a respawn after a
watchdog kill failing, the crash loop, and a respawn after a crash failing —
and only the crash loop wrote a marker. So the backstop covered one death path
in four, and the three it missed are the ones where the worker never came back
at all. That is not a coverage hole; it is the defect the comment describes,
alive in three quarters of its cases.

⭐ THE PINS ARE STRUCTURAL, over the parse tree. A `toContain` on source cannot
tell a call inside the right branch from one in a comment or a dead `if`, and
this is a 780-line supervisor loop with four near-identical branches.
"""
import ast
import inspect
import json
import time
from pathlib import Path

import pytest

import research


def _fn(name):
    src = Path(research.__file__).with_name("research.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in research.py")


def _calls_named(node, name):
    out = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == name:
            out.append(sub)
    return out


def _dead_assignments(node):
    """Every `{"_dead": True}` dict literal inside `node`, by line."""
    out = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Dict):
            continue
        for k, v in zip(sub.keys, sub.values):
            if (isinstance(k, ast.Constant) and k.value == "_dead"
                    and isinstance(v, ast.Constant) and v.value is True):
                out.append(sub.lineno)
    return sorted(out)


# ══ 1. every way the supervisor gives up must leave a marker ═══════════
def test_the_supervisor_declares_a_worker_dead_in_exactly_four_places():
    """⭐ THE COUNT IS THE GUARD. A fifth branch added without a marker is the
    way this regresses, and the only thing that would notice is a number."""
    sites = _dead_assignments(_fn("run_daemon_loop"))
    assert len(sites) == 4, (
        f"expected 4 `_dead` declarations in run_daemon_loop, found {len(sites)} "
        f"at lines {sites} — a new one needs a dead-marker beside it")


def test_every_dead_declaration_writes_the_marker_that_rescues_its_runs():
    """⛔⛔ THE DEFECT. Three of the four wrote nothing, so worker 1's
    reconciler could not see those deaths and the runs they abandoned stayed
    frozen with no Resume."""
    fn = _fn("run_daemon_loop")
    dead_lines = _dead_assignments(fn)
    marker_lines = [c.lineno for c in _calls_named(fn, "_write_worker_dead_marker")]
    assert marker_lines, "the supervisor never writes a dead-marker at all"
    for ln in dead_lines:
        near = [m for m in marker_lines if abs(m - ln) <= 12]
        assert near, (
            f"the `_dead` declaration at line {ln} writes no dead-marker — "
            f"worker 1 cannot see this death and the runs it abandoned keep no "
            f"Resume. Marker writes are at {marker_lines}")


def test_each_death_says_which_kind_it_was():
    """⭐ Four outcomes, four reasons. The field is diagnostics — nothing reads
    it — and a literal "crash_loop" on all four is precisely why three missing
    call sites went unnoticed for two months."""
    fn = _fn("run_daemon_loop")
    reasons = set()
    for call in _calls_named(fn, "_write_worker_dead_marker"):
        for kw in call.keywords:
            if kw.arg == "reason" and isinstance(kw.value, ast.Constant):
                reasons.add(kw.value.value)
    # three explicit + one that takes the default
    assert len(reasons) >= 3, f"death reasons are not distinct: {reasons}"
    assert "spawn_failed_at_boot" in reasons


def test_the_marker_records_the_reason_it_was_given(tmp_path, monkeypatch):
    """The unit under the structure — and the default stays what it was, so the
    crash-loop branch's marker is byte-compatible with the readers."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    research._write_worker_dead_marker(3, pid=4242, crash_count=5,
                                       reason="respawn_failed_after_crash")
    rec = json.loads(research._worker_dead_marker_path(3).read_text(encoding="utf-8"))
    assert rec["reason"] == "respawn_failed_after_crash"
    assert rec["worker_id"] == 3 and rec["pid"] == 4242 and rec["crash_count"] == 5
    research._write_worker_dead_marker(4)
    rec4 = json.loads(research._worker_dead_marker_path(4).read_text(encoding="utf-8"))
    assert rec4["reason"] == "crash_loop", "the default reason changed under the readers"


def test_the_reader_does_not_care_which_reason_it_was(tmp_path, monkeypatch):
    """⛔ THE OVER-CORRECTION GUARD. If `_read_dead_worker_ids` ever started
    filtering on `reason`, the three newly-marked paths would go dark again
    while every test above stayed green."""
    monkeypatch.setattr(research, "__file__", str(tmp_path / "research.py"))
    for wid, why in ((2, "spawn_failed_at_boot"), (3, "respawn_failed_after_watchdog")):
        research._write_worker_dead_marker(wid, reason=why)
    # settle past the grace window the reader applies
    for wid in (2, 3):
        p = research._worker_dead_marker_path(wid)
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec["died_at"] = int(time.time() * 1000) - (research.DEAD_WORKER_MARKER_GRACE_MS + 5_000)
        p.write_text(json.dumps(rec), encoding="utf-8")
    # ⛔ `load_worker_count()`, NOT a module constant — the reader calls the
    # loader on every read so a fleet resize takes effect without a restart. My
    # first attempt patched a constant that does not exist and the test told me
    # so by dropping exactly one of the two markers.
    monkeypatch.setattr(research, "load_worker_count", lambda: 4)
    found = research._read_dead_worker_ids()
    assert {2, 3} <= set(found), f"the reader dropped a death by its reason: {found}"


# ══ 2. the three lines that make the mechanism run ═════════════════════
def test_worker_one_actually_starts_the_reconciler():
    """⛔⛔ UNPINNED UNTIL NOW. Fifteen tests drive the reconciler as a function;
    nothing asserted anything ever calls it. Delete this one line and every one
    of them still passes while no orphaned run is ever marked again."""
    fn = _fn("run_server")
    started = [
        c for c in ast.walk(fn)
        if isinstance(c, ast.Call)
        and isinstance(c.func, ast.Attribute) and c.func.attr == "create_task"
        and c.args and isinstance(c.args[0], ast.Call)
        and isinstance(c.args[0].func, ast.Name)
        and c.args[0].func.id == "_dead_worker_reconcile_loop"
    ]
    assert len(started) == 1, (
        "`_dead_worker_reconcile_loop` is not scheduled exactly once in "
        f"run_server (found {len(started)}) — the backstop's helpers all still "
        "pass their own tests")


def test_the_SUPERVISOR_never_retracts_a_marker():
    """⛔⛔ THIS TEST ASSERTED THE OPPOSITE ONE ROUND AGO, AND IT WAS WRONG.

    Round one found the marker outliving a successful retry, so the repair made
    every successful respawn retract it — three call sites — and this test
    counted them. Round two then proved the premise false by reading
    `_spawn_worker`: it returns the instant `Popen` succeeds. No health check,
    no poll, no port probe after launch. So "a worker that came up" is not what
    those branches measured, and a worker that dies at import had its marker
    cleared about SEVEN SECONDS after it was written — never reaching the
    reader's sixty-second grace. The repair deleted the rescue it was widening,
    and the test counted call sites, which is satisfied identically by three
    correct retractions and three harmful ones.

    ⭐ THE CHILD'S OWN `--serve` BOOT IS THE ONLY HONEST RETRACTION: a process
    that reaches there is, by construction, alive. And nothing may retract at
    BOOT — a marker left by the previous supervisor session is the whole reason
    the mechanism exists.
    """
    fn = _fn("run_daemon_loop")
    clears = _calls_named(fn, "_clear_worker_dead_marker")
    assert clears == [], (
        f"the supervisor retracts a dead-marker at {[c.lineno for c in clears]} — "
        f"`_spawn_worker` returns on a successful fork, not a live worker, so "
        f"this clears markers for workers that are genuinely dead before the "
        f"reader's grace window can ever see them")


def test_the_only_retraction_is_the_child_proving_itself_alive():
    """⭐ ACCEPT POLARITY for the refusal above. Removing every retraction would
    strand a repaired worker's runs for ever, which is the opposite failure."""
    fn = _fn("run_server")
    assert _calls_named(fn, "_clear_worker_dead_marker"), (
        "nothing retracts a dead-marker at all — a repaired worker stays dead "
        "to the reconciler for ever")


def test_a_worker_that_boots_retracts_its_own_marker():
    """⛔ THE OTHER HALF OF THE SAME MECHANISM. Without the retraction an
    operator repair needs a manual step nobody documents, and worker 1
    re-pauses the runs the repaired worker is about to pick up."""
    fn = _fn("run_server")
    assert _calls_named(fn, "_clear_worker_dead_marker"), (
        "nothing retracts a dead-marker on boot — a repaired worker stays dead "
        "to the reconciler for ever")


def test_the_reconciler_is_only_ever_driven_with_the_paired_owner_tree():
    """⭐ RECORDED, NOT FIXED. `_reconcile_dead_worker_runs`'s docstring argues
    at length that its tree is always the paired owner, and that argument is
    correct about permissions and silent about coverage: a run submitted by a
    SHARER lives in the sharer's tree, which this never queries. Pinning the
    single call site is what will make that visible the day it changes."""
    fn = _fn("run_server")
    sites = _calls_named(fn, "_reconcile_dead_worker_runs")
    assert len(sites) == 1, f"expected exactly one caller, found {[c.lineno for c in sites]}"
    # ⛔ THE PROPERTY, NOT THE SPELLING. My first attempt demanded the call
    # literally contain `load_paired_uid()` and failed on correct code — the
    # uid is bound to a local three lines earlier. What matters is that the
    # tree it passes CAME from the paired owner, whatever it is called.
    loop = _fn("_dead_worker_reconcile_loop")
    from_paired = {
        t.id
        for node in ast.walk(loop) if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "load_paired_uid"
    }
    assert from_paired, "the reconcile loop no longer resolves the paired owner at all"
    first = sites[0].args[0] if sites[0].args else None
    assert isinstance(first, ast.Name) and first.id in from_paired, (
        "the reconciler is now driven with a tree that did not come from "
        "load_paired_uid — its docstring's permission argument no longer holds, "
        "and the sharer-tree gap it never covered has just changed shape")


def test_the_backstop_helpers_are_all_still_module_level():
    """⭐ CHEAP, AND IT IS THE THING THAT BROKE LAST TIME. Every pin above reads
    the parse tree by function name; a helper folded into a closure would make
    all of them vacuous rather than red."""
    for name in ("_write_worker_dead_marker", "_clear_worker_dead_marker",
                 "_read_dead_worker_ids", "_reconcile_dead_worker_runs"):
        assert callable(getattr(research, name, None)), f"{name} is no longer module-level"
    assert inspect.iscoroutinefunction(research._reconcile_dead_worker_runs)
