"""The device advertised two workers and ran one, so the second run never queued.

WHAT HAPPENED (2026-08-11)

The owner fired a run, then fired a second one. It should have shown "queued".
Instead the app opened a Phase 0 tile that sat at Init and then said
"Macbook isn't responding" — while the researches list, reading backend truth,
showed the same run as `queued`. Two surfaces, two answers, one run.

The backend was right the whole way through:

    18:26:47  run dir created for the first run
    18:27:08  [start-listener] worker 1: defer … reason=busy-running

It deferred, wrote no run dir, and waited. The app is what went wrong, and it
went wrong because of something the backend told it.

  * `research_config.json` says `workerCount: 2` — this device has two browser
    PROFILES set up.
  * Profiles are not workers. Workers 2..N exist only when `run_daemon_loop`
    spawns them. A foreground `--serve` is one process with one browser.
  * The heartbeat published the configured number anyway.

So the app computed capacity 2, saw one run active, concluded a worker was
free, and took the "start it now" branch: no optimistic queue tile, an inline
await with a ~15s deadline, and — when nobody claimed the run, because the
backend had correctly deferred it — a timeout, a stale-heartbeat verdict, and a
Phase 0 tile the app minted itself so the alert had somewhere to dock.

THE DISCRIMINATOR, AND WHY THE OBVIOUS ONES ARE WRONG

`WORKER_ID` is 1 in all three of these, which have different capacities:

    foreground `--serve`                  1 slot   (no --worker-id)
    supervised single-worker child        1 slot   (no --worker-id)
    fleet member #1 under daemon-loop     N slots  (--worker-id 1)

`_detect_supervised()` is wrong too: it probes whether the launchd/schtasks job
EXISTS, so it answers True for a foreground serve on any machine that also has
On Startup enabled — which is most of them.

What actually separates them is the flag daemon-loop passes to its fleet and to
nothing else. Hence `_FLEET_MEMBER`, set from the flag's PRESENCE (`--worker-id 1`
is a fleet member; no flag is not), which is why argparse's default had to
become None.

WHAT THESE TESTS PIN

  1. A standalone serve publishes 1 no matter what the config says.
  2. A fleet member publishes the configured N — the supervised path is
     untouched, which is the constraint the owner set on this fix.
  3. The presence/value distinction survives, argparse default included.
  4. The heartbeat publishes running capacity; a revert to the configured
     count fails on the syntax tree, not on a substring.
  5. ⭐ The multi-worker queue protections are all still standing: the defer
     gate still keys on the CONFIGURED count (so this fix did not quietly
     disable deferral), the settle window and its sibling re-check are intact,
     idle-rescan still sorts FIFO, and daemon-loop still spawns its fleet with
     --worker-id and its single-worker child without one.
"""
import ast
import functools
import inspect
import io
import textwrap
import tokenize

import pytest

import research


@functools.lru_cache(maxsize=1)
def module_src() -> str:
    """The whole module, comments blanked. Read once for the file."""
    return code_only(inspect.getsource(research))


@functools.lru_cache(maxsize=8)
def code_only(src: str) -> str:
    """`src` with comments blanked out, offsets preserved.

    Same helper, same reason as test_share_links_0811: this file asserts that
    the heartbeat no longer reads the configured count, and the comment sitting
    directly above the fix quotes `load_worker_count()` while explaining it.
    Prose that documents a call is not the call.

    Line offsets are precomputed and the result memoised — several tests here
    blank the WHOLE 64k-line module, and recomputing the offset of every
    comment by re-summing the lines above it made one test file take minutes."""
    out = list(src)
    starts, pos = [], 0
    for line in src.splitlines(keepends=True):
        starts.append(pos)
        pos += len(line)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.COMMENT:
                continue
            (srow, scol), (erow, ecol) = tok.start, tok.end
            if srow != erow or srow > len(starts):
                continue
            line_start = starts[srow - 1]
            for i in range(line_start + scol, min(line_start + ecol, len(out))):
                out[i] = " "
    except (tokenize.TokenError, IndentationError):
        return src
    return "".join(out)


@pytest.fixture
def fleet(monkeypatch):
    """Set (_FLEET_MEMBER, configured profile count) for one test."""
    def _set(is_fleet_member: bool, configured: int):
        monkeypatch.setattr(research, "_FLEET_MEMBER", is_fleet_member)
        monkeypatch.setattr(research, "load_worker_count", lambda: configured)
    return _set


# ---------------------------------------------------------------- capacity


@pytest.mark.parametrize("configured", [1, 2, 3, 5])
def test_a_standalone_serve_has_one_slot_whatever_the_config_says(fleet, configured):
    """THE BUG. One process, one browser, one slot — every time."""
    fleet(False, configured)
    assert research._running_worker_capacity() == 1


def test_the_exact_broken_case_two_profiles_one_foreground_serve(fleet):
    """The owner's machine on 2026-08-11, verbatim."""
    fleet(False, 2)
    assert research._running_worker_capacity() == 1, (
        "a foreground serve on a 2-profile device published 2, and that is the "
        "entire reason the second run stalled at Init instead of queueing"
    )


@pytest.mark.parametrize("configured", [1, 2, 3, 4, 8])
def test_a_fleet_member_still_publishes_the_configured_count(fleet, configured):
    """⛔ The supervised multi-worker queue must be untouched by this fix."""
    fleet(True, configured)
    assert research._running_worker_capacity() == configured


def test_a_fleet_member_reads_the_config_rather_than_assuming(fleet, monkeypatch):
    """Not a literal, not WORKER_ID — the configured count, read at call time."""
    calls = []
    monkeypatch.setattr(research, "_FLEET_MEMBER", True)
    monkeypatch.setattr(research, "load_worker_count",
                        lambda: (calls.append(1), 3)[1])
    assert research._running_worker_capacity() == 3
    assert calls, "a fleet member must ASK how many profiles are configured"


def test_capacity_is_never_zero_or_negative(fleet):
    """A 0 here would make the app think the device can never run anything."""
    for member in (True, False):
        for configured in (0, -1, 1):
            fleet(member, max(1, configured))
            assert research._running_worker_capacity() >= 1


# ------------------------------------------------------ the discriminator


def test_the_worker_id_flag_defaults_to_none_not_one():
    """The whole fix rests on this: with default=1, `--worker-id 1` and "no
    flag at all" arrive identical and a fleet member is indistinguishable from
    a foreground serve."""
    src = module_src()
    tree = ast.parse(src)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", "") != "add_argument":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        if node.args[0].value != "--worker-id":
            continue
        for kw in node.keywords:
            if kw.arg == "default":
                found.append(ast.literal_eval(kw.value))
    assert found, "--worker-id is no longer declared"
    assert found == [None], (
        f"--worker-id default is {found!r}; it must be None so the PRESENCE of "
        f"the flag stays readable"
    )


def test_worker_id_still_resolves_to_one_when_the_flag_is_absent():
    """Backward compatibility: nothing downstream may start seeing None."""
    src = module_src()
    assert "WORKER_ID = max(1, int(args.worker_id or 1))" in src, (
        "the None default must still be normalised to 1 for WORKER_ID"
    )


def test_fleet_membership_is_read_from_presence_not_from_the_value():
    """`args.worker_id == 1` would call fleet member #1 a foreground serve."""
    src = module_src()
    assert "_FLEET_MEMBER = args.worker_id is not None" in src
    for wrong in ("args.worker_id == 1", "args.worker_id > 1", "args.worker_id or 1) > 1"):
        assert f"_FLEET_MEMBER = {wrong}" not in src


def test_fleet_membership_defaults_to_false_at_module_scope():
    """Any process that never parsed args — a test, an import, a helper CLI —
    must read as standalone, not silently claim N slots."""
    tree = ast.parse(module_src())
    defaults = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and getattr(node.target, "id", "") == "_FLEET_MEMBER"
        and isinstance(node.value, ast.Constant)
    ]
    assert defaults == [False]


def test_the_global_is_declared_before_it_is_assigned():
    """A missing `global` would make the assignment local and the flag would
    never take effect — the fix would be a no-op that still passes a unit test
    on the function itself."""
    src = module_src()
    assert "global WORKER_ID, _FLEET_MEMBER" in src


# ------------------------------------------------- the heartbeat publishes it


def _heartbeat_src():
    return code_only(inspect.getsource(research._heartbeat_loop))


def test_the_heartbeat_publishes_running_capacity():
    """Asserted on the syntax tree: the value assigned to `_wc_payload` must BE
    a call to `_running_worker_capacity`, not merely mention it."""
    tree = ast.parse(textwrap.dedent(_heartbeat_src()))
    assigned = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", "") == "_wc_payload" for t in node.targets):
            continue
        assigned.append(getattr(node.value.func, "id", None)
                        if isinstance(node.value, ast.Call) else "<not-a-call>")
    assert assigned == ["_running_worker_capacity"], (
        f"_wc_payload is built from {assigned!r} — the heartbeat must publish "
        f"what this process RUNS, not what the device has profiles for"
    )


def test_the_heartbeat_no_longer_reads_the_configured_count():
    """Comment-blanked, so the paragraph explaining the fix cannot satisfy it."""
    assert "load_worker_count()" not in _heartbeat_src()


def test_the_published_field_is_the_computed_payload():
    """A literal, or a second call, would drift from `_wc_payload` silently."""
    src = _heartbeat_src()
    assert '"workerCount": _wc_payload,' in src


def test_only_the_heartbeat_writes_workercount_to_the_device_doc():
    """If a second publisher appears, this fix is half-applied and the two
    writers will fight over the field."""
    src = module_src()
    writes = [l for l in src.splitlines() if '"workerCount":' in l]
    assert len(writes) == 1, f"expected one publisher, found {len(writes)}: {writes}"


# --------------------------------------- ⛔ multi-worker must not regress


def _listener_src():
    """Source of the start-listener region that holds the defer gate."""
    src = module_src()
    i = src.index("_multi_worker_mode = load_worker_count() > 1")
    return src[i - 4000:i + 12000]


def test_the_defer_gate_still_keys_on_the_configured_count():
    """⭐ This fix changes what is PUBLISHED, not when the backend defers. If
    the gate ever read `_running_worker_capacity()` instead, a foreground serve
    on a 2-profile device would stop deferring and would claim both runs at
    once — strictly worse than the bug being fixed."""
    src = module_src()
    assert "_multi_worker_mode = load_worker_count() > 1" in src
    assert "_multi_worker_mode = _running_worker_capacity() > 1" not in src


def test_the_defer_gate_entry_condition_is_unchanged():
    """resting OR multi-worker OR a live rest episode — all three still open
    the gate."""
    assert 'if _resting or _multi_worker_mode or _REST_DEFER_SEEN["v"]:' in _listener_src()


def test_the_defer_gate_still_defers_on_every_busy_signal():
    src = _listener_src()
    for signal in ('_resting', '_QUEUE_STATE.get("running")',
                   'job_queue.qsize() > 0', '_pending_enq_read() > 0'):
        assert signal in src, f"the busy check lost {signal}"


def test_the_settle_window_and_sibling_recheck_survive():
    """Without these the 2-worker second fire flickers queued → ongoing."""
    src = _listener_src()
    assert "time.sleep(0.6)" in src, "the settle window is gone"
    assert '_q_data.get("assignedWorker")' in src, "the sibling re-check is gone"
    assert "skipping queued write" in src


def test_idle_rescan_still_sorts_fifo():
    """Stream order is by doc id, so without the sort the OLDEST orphan can sit
    under a newer one forever."""
    src = module_src()
    assert "def _fifo_key(_snap):" in src
    assert "candidates.sort(key=_fifo_key)" in src


def test_local_pending_owner_entries_still_keys_on_the_configured_count():
    """Its correctness depends on whether the listener DEFERS, which is the
    configured count — not on how many slots this process runs."""
    fn = code_only(inspect.getsource(research._local_pending_owner_entries))
    assert "load_worker_count() or 1) > 1" in fn
    assert "_running_worker_capacity" not in fn


def test_the_daemon_loop_spawns_its_fleet_with_worker_id():
    """The flag IS the discriminator; if the fleet stopped passing it, every
    supervised worker would publish 1 and multi-worker queueing would die."""
    src = code_only(inspect.getsource(research.run_daemon_loop))
    assert '"--worker-id", str(k)' in src


def test_the_supervised_single_worker_child_is_spawned_without_worker_id():
    """The other half of the discriminator. If this branch ever gained the
    flag, a 1-profile supervised install would still publish 1 — but the
    distinction this fix rests on would be gone, so pin it now."""
    src = code_only(inspect.getsource(research.run_daemon_loop))
    assert '[python_exe, script_path, "--serve", "--port", str(port)]' in src


def test_the_fleet_branch_still_triggers_on_more_than_one_profile():
    src = code_only(inspect.getsource(research.run_daemon_loop))
    assert "n_workers = load_worker_count()" in src
    assert "if n_workers > 1:" in src


# ------------------------------------------------------------- eta math


def test_queue_eta_with_one_slot_is_serial():
    """Publishing 1 feeds the ETA too — and for a foreground serve, serial is
    the truth. Position 2 waits a whole extra run; position 1 does not."""
    head = research._estimate_queue_eta_ms(0, 0, 1, 1)
    second = research._estimate_queue_eta_ms(0, 0, 2, 1)
    assert second > head


def test_queue_eta_with_two_slots_still_pairs():
    """Unchanged for the supervised fleet: positions 1 and 2 share an ETA."""
    first = research._estimate_queue_eta_ms(0, 0, 1, 2)
    second = research._estimate_queue_eta_ms(0, 0, 2, 2)
    third = research._estimate_queue_eta_ms(0, 0, 3, 2)
    assert first == second < third


def test_queue_eta_is_never_negative():
    for w in (1, 2, 4):
        for pos in (1, 2, 5):
            assert research._estimate_queue_eta_ms(0, 0, pos, w) >= 0
