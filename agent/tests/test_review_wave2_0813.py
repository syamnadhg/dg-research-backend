"""Wave 2 of the 2026-08-13 repair plan — the two agent-side review findings.

  7. `ensure_durable_install()` had ONE rung. `pipx install --force` over a
     uv-backed venv fails outright on pipx 1.14/1.15 and only works from 1.16, a
     floor nothing in the repo stated, so those hosts came out of the bootstrap
     with no durable install — and therefore no login pin at all, since
     `cli._pin_startup` returns before `autostart.install()`. A non-destructive
     `pipx upgrade` retry now follows a failed force, and the pipx version is
     REPORTED on the failure rather than enforced as a block.

  8. The detached waiter's version comparator was unpadded where its
     `autostart` twin pads. `(0, 2) < (0, 2, 0)`, so `0.2` against a floor of
     `0.2.0` — the same release — read as behind, and `usable_install()` would
     call a good install unusable and send `_do_upgrade` on to the destructive
     branch. Not reachable while we only ship 3-segment versions; the padding is
     what keeps it that way.

⚠ Both live in code that is never IMPORTED in production shape: one is reached
only after a failure, the other ships as a `-c` string executed by a foreign
interpreter. So each test here either drives the real function against a
scripted pipx, or extracts the real payload and runs it. Neither re-implements
the logic it is checking.
"""
from __future__ import annotations

import ast
import subprocess

from facade import selfupdate


# ── the suite is testing THIS tree ───────────────────────────────────────────

def test_the_suite_is_testing_this_worktree() -> None:
    """Wave 1's scar, carried forward. A dev venv can hold an editable install
    of a DIFFERENT checkout, at which point `facade` has two possible answers
    and a green result means nothing. Fail here, loudly, rather than there."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]   # agent/tests -> repo
    got = pathlib.Path(selfupdate.__file__).resolve()
    assert got.parent.parent.parent == root, (
        f"the suite imported facade from {got}, which is not under {root} — "
        f"every assertion below is about a different copy of the code"
    )


# ── 7. the durable-install ladder ────────────────────────────────────────────

def _pipx(monkeypatch, *, script):
    """Record every pipx argv, and let `script` decide each call's exit code.

    `script` takes the argv and returns the returncode, so a test can fail the
    forced install and succeed the upgrade — the exact shape of the pipx
    1.14/1.15 uv failure this rung exists for.
    """
    seen: list = []

    def fake_run(argv, **kw):
        seen.append(list(argv))
        rc, out, err = script(list(argv))
        return subprocess.CompletedProcess(argv, rc, out, err)

    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate.subprocess, "run", fake_run)
    monkeypatch.setattr(selfupdate, "spawn_detached_cache_clear", lambda: True)
    return seen


def _uv_force_failure(argv):
    """Real pipx 1.15 + uv: the forced install refuses, an upgrade goes through."""
    if "install" in argv:
        return 1, "", "error: failed to create virtualenv: uv backend refused --force"
    if "upgrade" in argv:
        return 0, "upgraded superresearch-agent", ""
    if "--version" in argv:
        return 0, "1.15.0\n", ""
    return 0, "", ""


def test_a_failed_force_install_retries_without_tearing_anything_down(monkeypatch):
    """The finding. One rung meant one chance: a host whose pipx cannot do
    `install --force` finished the bootstrap with nothing durable, so the pin
    step was skipped and the bridge never came back after a reboot."""
    durable = iter([False, True])
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable",
                        lambda: next(durable))
    seen = _pipx(monkeypatch, script=_uv_force_failure)

    ok, note = selfupdate.ensure_durable_install()

    assert ok is True, f"the upgrade rung did not rescue the bootstrap: {note!r}"
    subs = [c[1] for c in seen]
    assert "install" in subs and "upgrade" in subs, f"rungs run: {subs!r}"
    assert subs.index("install") < subs.index("upgrade"), (
        "the layering upgrade ran BEFORE the clean forced install — `--force` is "
        f"the primary path precisely because upgrade layers: {subs!r}"
    )


def test_the_retry_is_never_an_uninstall(monkeypatch):
    """⛔ The over-correction that would re-open a finding the previous round
    closed. Uninstall-first is "the RECOVERY order, not the clean one" and "the
    only order that can leave the host with no agent at all"; this function had
    exactly that removed, and the fix for a FAILED install must not put it back.
    """
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable", lambda: False)
    seen = _pipx(monkeypatch, script=lambda argv: (1, "", "everything failed"))

    ok, _ = selfupdate.ensure_durable_install()

    assert ok is False
    assert not any(c[1] == "uninstall" for c in seen), (
        f"the failure path tore down the only working agent on the host: {seen!r}"
    )


def test_a_rung_one_that_RAISES_still_reaches_the_retry(monkeypatch):
    """An OSError is a rung-1 failure like any other, and the non-destructive
    retry is exactly as applicable to it. The first version returned early from
    the except, so the rescue was reachable only from a non-zero EXIT CODE — a
    distinction the caller has no reason to care about."""
    durable = iter([False, True])
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable",
                        lambda: next(durable))
    seen: list = []

    def fake_run(argv, **kw):
        seen.append(list(argv))
        if "install" in argv:
            raise OSError("connection reset by peer")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate.subprocess, "run", fake_run)
    monkeypatch.setattr(selfupdate, "spawn_detached_cache_clear", lambda: True)

    ok, _ = selfupdate.ensure_durable_install()
    assert ok is True, "a raised rung 1 skipped the rescue"
    assert any(c[1] == "upgrade" for c in seen), f"rungs run: {seen!r}"


def test_a_TIMEOUT_deliberately_does_not_reach_the_retry(monkeypatch):
    """⛔ The one exception that must NOT fall through, and the asymmetry is the
    point.

    `subprocess.run` kills and reaps the pipx process before raising — but pipx
    delegates to a pip/uv GRANDCHILD inside the target venv, which survives
    orphaned. A network-stalled pip can resume minutes later and write into the
    same venv while a retry is mutating it, and pipx takes no cross-process
    lock, so a half-merged venv could still satisfy the durability check and get
    pinned. Nothing is lost by refusing: the failure this ladder exists for is a
    non-zero EXIT, never a timeout."""
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable", lambda: False)
    seen: list = []

    def fake_run(argv, **kw):
        seen.append(list(argv))
        if "install" in argv:
            raise subprocess.TimeoutExpired(argv, 600)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate.subprocess, "run", fake_run)
    monkeypatch.setattr(selfupdate, "spawn_detached_cache_clear", lambda: True)

    ok, note = selfupdate.ensure_durable_install()
    assert ok is False
    assert not any(c[1] == "upgrade" for c in seen), (
        f"a timed-out install was retried while its pip grandchild may still be "
        f"writing to the same venv: {seen!r}")
    assert note, "the timeout was reported with no reason at all"


def test_a_raised_rung_one_still_reports_its_own_reason(monkeypatch):
    """And when the retry also fails, the exception's text is what the user
    needs — it must not be replaced by a generic line or blanked."""
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable", lambda: False)

    def fake_run(argv, **kw):
        if "install" in argv:
            raise OSError("index unreachable: name resolution failed")
        return subprocess.CompletedProcess(argv, 1, "", "")

    monkeypatch.setattr(selfupdate, "_pipx_cmd", lambda: ["pipx"])
    monkeypatch.setattr(selfupdate.subprocess, "run", fake_run)
    monkeypatch.setattr(selfupdate, "spawn_detached_cache_clear", lambda: True)

    ok, note = selfupdate.ensure_durable_install()
    assert ok is False
    assert "index unreachable" in note, f"the raised reason was lost: {note!r}"


def test_the_happy_path_still_costs_exactly_one_pipx_call(monkeypatch):
    """⛔ The other over-correction: probing the pipx version, or trying the
    upgrade anyway, would add minutes of subprocess round-trips to the path
    every healthy host takes. The extra rungs exist for a failure, and must be
    reachable only from one."""
    durable = iter([False, True])
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable",
                        lambda: next(durable))
    seen = _pipx(monkeypatch, script=lambda argv: (0, "", ""))

    assert selfupdate.ensure_durable_install()[0] is True
    assert seen == [["pipx", "install", "--force", selfupdate._agent_floor_spec()]], (
        f"a successful bootstrap ran more than the one install: {seen!r}"
    )


def test_an_old_pipx_is_named_on_the_failure_but_never_refused(monkeypatch):
    """The floor is stated as CONTEXT, deliberately. It was measured against the
    uv backend only, and plenty of hosts on an older pipx run the pip backend
    where `--force` works — refusing on the version would break those installs
    to prevent a failure they would never have had."""
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable", lambda: False)

    def script(argv):
        if "--version" in argv:
            return 0, "1.15.0\n", ""
        return 1, "", "uv backend refused --force"

    seen = _pipx(monkeypatch, script=script)
    ok, note = selfupdate.ensure_durable_install()

    assert ok is False
    assert "uv backend refused --force" in note, "pipx's own reason was dropped"
    assert "1.15.0" in note and selfupdate.PIPX_MIN_FOR_FORCE in note, (
        f"the note does not name the installed pipx and the tested floor: {note!r}"
    )
    assert any(c[1] == "install" for c in seen), (
        "it refused on the version instead of attempting the install — a warning "
        "that blocks is a block"
    )


def test_a_modern_pipx_adds_no_note(monkeypatch):
    """Guard against the guard: the note must be conditional on the version, not
    stapled to every failure."""
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable", lambda: False)

    def script(argv):
        if "--version" in argv:
            return 0, "1.16.5\n", ""
        return 1, "", "no matching distribution"

    _pipx(monkeypatch, script=script)
    _, note = selfupdate.ensure_durable_install()
    assert note == "no matching distribution", f"a modern pipx was warned about: {note!r}"


def test_an_unreadable_pipx_version_adds_no_note(monkeypatch):
    """Never manufacture a diagnosis. A pipx that cannot report its version says
    nothing about whether it is the cause."""
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable", lambda: False)

    for version_answer in ((1, "", ""), (0, "", ""), (0, "not-a-version\n", "")):
        def script(argv, _v=version_answer):
            if "--version" in argv:
                return _v
            return 1, "", "boom"

        _pipx(monkeypatch, script=script)
        _, note = selfupdate.ensure_durable_install()
        assert note == "boom", f"{version_answer!r} produced a warning: {note!r}"


def test_an_upgrade_that_exits_zero_without_a_durable_target_is_not_success(monkeypatch):
    """The same rule the forced install already follows: a pipx exit code is not
    a post-condition. An upgrade that reports success while the package
    directory still cannot be resolved would send the caller on to pin the cache
    path — the exact bug this whole function exists to prevent."""
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable", lambda: False)
    _pipx(monkeypatch, script=lambda argv: (0, "", "") if "upgrade" in argv
          else (1, "", "force failed"))

    ok, note = selfupdate.ensure_durable_install()
    assert ok is False, "a zero exit was taken as proof the install landed"
    assert "force failed" in note


def test_the_cleaner_is_spawned_with_our_distribution_name(monkeypatch, tmp_path):
    """Found by the mutation run, not by review: nothing asserted what the
    CALLER passes.

    The waiter's literal fallback is a safety net for an older caller, not the
    contract. With the caller passing the wrong name the cleaner matches nothing
    and deletes nothing while reporting that it cleaned up — which is precisely
    the failure of the directory-name filter it replaced, arriving by a
    different route. Every test on the cleaner itself invokes the payload
    directly, so all of them stayed green."""
    seen: list = []
    monkeypatch.setattr(selfupdate, "_pipx_cache_dir", lambda: str(tmp_path))
    monkeypatch.setattr(selfupdate, "_waiter_python", lambda: "python3")
    monkeypatch.setattr(selfupdate, "_spawn_detached",
                        lambda cmd, log: seen.append(list(cmd)) or True)

    assert selfupdate.spawn_detached_cache_clear() is True
    assert seen, "the cleaner was never spawned"
    assert seen[0][-1] == selfupdate.AGENT_PKG, (
        f"the cleaner was told to look for {seen[0][-1]!r} rather than our own "
        f"distribution ({selfupdate.AGENT_PKG!r}) — it will match nothing"
    )


def test_a_rescued_bootstrap_still_drops_the_stale_run_cache(monkeypatch):
    """`pipx run` reuses its venv for ~14 days. Whichever rung succeeded, leaving
    the cache behind means a later bootstrap can replay a build older than the
    one just installed."""
    durable = iter([False, True])
    monkeypatch.setattr(selfupdate.autostart, "pin_target_is_durable",
                        lambda: next(durable))
    cleared: list = []
    _pipx(monkeypatch, script=_uv_force_failure)
    monkeypatch.setattr(selfupdate, "spawn_detached_cache_clear",
                        lambda: cleared.append(True) or True)

    assert selfupdate.ensure_durable_install()[0] is True
    assert cleared == [True], "the upgrade rung left the stale run-cache venv behind"


# ── 8. the waiter's version comparator ───────────────────────────────────────

def _waiter_fns(*names, **inject):
    """Extract named functions from the `-c` waiter payload and make them
    callable.

    The waiter is a STRING run by a foreign interpreter — nothing imports it, so
    there is no other way to exercise the real arithmetic. Re-typing it into the
    test would be testing the copy, which is the failure mode that let the two
    twins diverge in the first place."""
    tree = ast.parse(selfupdate._RECONNECT_WAITER)
    wanted = [n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in wanted} == set(names), (
        f"the waiter no longer defines {sorted(set(names) - {n.name for n in wanted})} "
        f"at top level — this test is now checking nothing"
    )
    ns: dict = dict(inject)
    exec(compile(ast.Module(body=wanted, type_ignores=[]),
                 "<reconnect-waiter>", "exec"), ns)
    return ns


def test_the_same_release_written_two_ways_compares_equal():
    """The defect. `0.2` and `0.2.0` are one release; unpadded tuples rank the
    shorter one BELOW the longer, so a good install failed `usable_install()`
    and `_do_upgrade` went on to uninstall it."""
    ns = _waiter_fns("_ver", "_ver_ge")
    assert ns["_ver_ge"]("0.2", "0.2.0") is True
    assert ns["_ver_ge"]("0.2.0", "0.2") is True
    assert ns["_ver_ge"]("0.1.32", "0.1.32") is True


def test_padding_does_not_make_everything_pass():
    """⛔ The over-correction. A comparator that always says yes would satisfy
    the test above perfectly and turn `usable_install()` — the post-condition
    that exists because a pipx exit code is not one — into a constant True."""
    ns = _waiter_fns("_ver", "_ver_ge")
    assert ns["_ver_ge"]("0.1.31", "0.1.32") is False
    assert ns["_ver_ge"]("0.1", "0.2") is False
    assert ns["_ver_ge"]("0.9.9", "1.0") is False
    assert ns["_ver_ge"]("1.0", "0.9.9") is True


def test_the_waiter_comparator_agrees_with_its_autostart_twin():
    """The twins have drifted once already, which is how this shipped. Same
    questions, same answers — checked against the real `autostart._ver_ge`, not
    a restatement of it."""
    from facade import autostart
    ns = _waiter_fns("_ver", "_ver_ge")
    for a, b in (("0.2", "0.2.0"), ("0.2.0", "0.2"), ("0.1.32", "0.1.31"),
                 ("0.1.31", "0.1.32"), ("1.0", "0.9.9"), ("0.1.9", "0.1.10")):
        assert ns["_ver_ge"](a, b) == autostart._ver_ge(a, b), (
            f"the waiter and autostart disagree on {a} >= {b}"
        )


def _usable_install(*, version, floor, entry="/venvs/superresearch-agent/bin/agent"):
    """Execute the waiter's REAL `usable_install`, with its collaborators
    injected.

    ⚠ This replaces a pair of source-substring assertions — `"_ver_ge(v, floor)"
    in src` and `"_ver(v) >= _ver(floor)" not in src`. The first is satisfied by
    a COMMENT; the second is whitespace-exact. Both stayed green against a
    reverted waiter carrying `return not (v and floor) or _ver(v)>=_ver(floor)`
    with the old expression in a trailing comment — i.e. the shipped defect
    fully restored, which is precisely the "unused helper next to an unpadded
    inline compare" shape the old docstring warned about while being unable to
    detect it.
    """
    ns = _waiter_fns("_ver", "_ver_ge", "usable_install",
                     installed_entry=lambda: entry,
                     installed_version=lambda: version,
                     floor=floor)
    return ns["usable_install"]()


def test_usable_install_actually_routes_through_the_padded_comparator():
    """⭐ The verdict, executed. `0.2` against a floor of `0.2.0` is the SAME
    release; unpadded it reads as behind, `usable_install` calls a working
    install unusable, and `_do_upgrade` goes on to the destructive branch."""
    assert _usable_install(version="0.2", floor="0.2.0") is True
    assert _usable_install(version="0.2.0", floor="0.2") is True


def test_usable_install_still_refuses_a_genuinely_older_build():
    """⛔ Over-correction: a verdict that always says yes turns the one
    post-condition guarding a pipx exit code into a constant True."""
    assert _usable_install(version="0.1.31", floor="0.1.32") is False
    assert _usable_install(version="0.9.9", floor="1.0") is False


def test_usable_install_still_refuses_a_venv_with_no_console_script():
    """The other half it has always checked: rc 0 with no entry point is the
    half-broken venv a failed uninstall leaves behind."""
    assert _usable_install(version="9.9.9", floor="0.1.0", entry=None) is False


def test_an_unreadable_version_is_treated_as_fine():
    """Deliberate, and worth pinning: refusing on a bookkeeping hiccup would
    trigger a destructive repair over nothing."""
    assert _usable_install(version=None, floor="0.1.32") is True
