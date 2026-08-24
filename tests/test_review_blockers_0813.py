"""The three blocking findings from the 2026-08-12 review of PR #4.

  1. `_reclaim_port` signalled every holder it recognised, with no test of
     whether that holder was doing anything — so a second `--serve` ended a
     healthy run.
  2. The Claude model picker accepted a billing chip as a model row, clicked it,
     and reported the click as a successful selection.
  3. A refused Restart replaced the whole `updateStatus` map, deleting the
     `needsRestart` flag the Restart button is rendered from.

⭐ Each fix is tested in BOTH directions. All three findings are about a guard
that was missing; the cheapest wrong fix for every one of them is a guard that
refuses everything, which looks like safety and silently deletes the feature.
The over-correction cases here are the ones that would catch that:

  * `test_an_idle_holder_is_still_reclaimed` and
    `test_a_holder_that_does_not_answer_at_all_is_still_reclaimed` fail if the
    busy guard is widened.
  * `test_the_health_STATUS_probe_is_not_what_gates_the_reclaim` fails if
    someone takes the review's literal suggestion, which would refuse every
    reclaim.
  * `test_a_versionless_family_row_is_still_picked` fails if the upsell fix is
    written as "require a version", which is the review's second suggestion and
    would empty the menu on a rename.
"""

from __future__ import annotations

import ast
import inspect
import io
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import models  # noqa: E402
import research  # noqa: E402

from _domshim import NODE, el, js_constant, run_js  # noqa: E402
from conftest import apply_firestore_update  # noqa: E402


def test_the_suite_is_testing_THIS_tree():
    """⛔ The dev venv carries an EDITABLE INSTALL of the personal checkout, so
    `import research` has two possible answers on this machine: this worktree,
    or `dg-research-backend`. Which one wins is a `sys.path` accident.

    That is not a theoretical worry — it is how a mutation run over this wave
    reported holes that did not exist. A test process resolving the other copy
    sees UNMUTATED source, every assertion passes, and the harness records the
    suite as blind to a defect it actually catches. The same accident would let
    a whole green suite certify a tree nobody edited.

    Cheap, and it fails loudly at the one moment it matters."""
    root = pathlib.Path(__file__).resolve().parents[1]
    for mod in (research, models):
        got = pathlib.Path(mod.__file__).resolve()
        assert got.parent == root, (
            f"{mod.__name__} resolved to {got}, not this worktree ({root}). "
            f"Every result in this file would be about the wrong code.")


# ══════════════════════════════════════════════════════════════════════════
# Finding 1 — a second `--serve` must not end a run that is in flight
# ══════════════════════════════════════════════════════════════════════════


class _FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def fake_health(monkeypatch):
    """Serve a chosen /api/health body to `_port_backend_activity`."""

    def _install(body, *, status=200, raises=False):
        import urllib.request as _u

        def _urlopen(url, timeout=None):
            if raises:
                raise OSError("connection refused")
            payload = body if isinstance(body, bytes) else json.dumps(body).encode()
            return _FakeResponse(payload, status)

        monkeypatch.setattr(_u, "urlopen", _urlopen)

    return _install


@pytest.mark.parametrize(
    "activity,expected",
    [
        (None, False),                                  # nothing answered
        ({}, False),
        ({"running": False, "pending": 0}, False),       # idle → reclaimable
        ({"running": True, "pending": 0}, True),         # a pipeline is executing
        ({"running": False, "pending": 3}, True),        # jobs are queued
        ({"running": True, "pending": 9}, True),
    ],
)
def test_what_counts_as_work(activity, expected):
    """The DECISION, isolated from the socket. `running` OR `pending` — the same
    two facts the restart and update command handlers already refuse on."""
    assert research._backend_activity_is_work(activity) is expected


def test_the_activity_probe_reads_the_body_not_the_status_line(fake_health):
    fake_health({"status": "ok", "running": True, "pending": 2})
    assert research._port_backend_activity(8000) == {"running": True, "pending": 2}


def test_the_probe_asks_the_endpoint_that_actually_publishes_those_fields(monkeypatch):
    """⭐ THE WIRING, which nothing asserted. The consumer's parsing is pinned
    above, the producer's fields are pinned below — and between them sat the URL,
    checked by no test in the suite.

    A typo there (`/api/healthz`, the wrong port variable) makes every real probe
    404, which parses to None, which reads as "not working" — and finding 1 is
    fully back with every one of these tests still green."""
    import urllib.request as _u
    seen: list = []

    def _spy(url, timeout=None):
        seen.append(url)
        return _FakeResponse(json.dumps({"status": "ok", "running": True}).encode(), 200)

    monkeypatch.setattr(_u, "urlopen", _spy)
    research._port_backend_activity(8123)
    assert seen == ["http://127.0.0.1:8123/api/health"], (
        f"the activity probe asked {seen!r} — the port it was given and the "
        f"endpoint that publishes running/pending are both part of the fix"
    )


def test_a_non_2xx_answer_is_not_an_activity_reading(fake_health):
    fake_health({"status": "ok", "running": True}, status=503)
    assert research._port_backend_activity(8000) is None


@pytest.mark.parametrize("body", [b"not json", b"[]", b'"ok"'])
def test_an_unparseable_answer_is_not_an_activity_reading(fake_health, body):
    fake_health(body)
    assert research._port_backend_activity(8000) is None


def test_an_unreachable_port_answers_None_not_idle(fake_health):
    """⚠ The distinction the caller depends on: None means "nothing answered",
    which is NOT the same claim as "answered, and is idle"."""
    fake_health({}, raises=True)
    assert research._port_backend_activity(8000) is None


def test_a_nonnumeric_pending_does_not_crash_the_probe(fake_health):
    fake_health({"status": "ok", "running": False, "pending": "many"})
    assert research._port_backend_activity(8000) == {"running": False, "pending": 0}


def test_silence_is_asked_more_than_once_before_it_counts_as_idle(monkeypatch):
    """⭐ This repo already knew a working worker can go quiet: the supervisor
    watchdog allows a mid-run worker 420 SECONDS of silence, on the stated
    grounds that "runs can briefly block the loop". Against that, one 3-second
    probe treating a quiet holder as idle is not a liveness test — it kills the
    busiest workers preferentially, three hours into a run, for one blocking
    section."""
    import urllib.request as _u
    monkeypatch.setattr(research.time, "sleep", lambda *_a: None)
    answers = [None, None, {"status": "ok", "running": True, "pending": 0}]
    calls = {"n": 0}

    def _flaky(url, timeout=None):
        body = answers[min(calls["n"], len(answers) - 1)]
        calls["n"] += 1
        if body is None:
            raise OSError("connection refused")
        return _FakeResponse(json.dumps(body).encode(), 200)

    monkeypatch.setattr(_u, "urlopen", _flaky)
    got = research._probe_backend_activity_until_settled(8000, settle_s=5.0)
    assert got == {"running": True, "pending": 0}, (
        "a worker that answered on the third probe was recorded as idle"
    )
    assert calls["n"] == 3


def test_a_holder_that_never_answers_is_still_read_as_not_working(monkeypatch):
    """⛔ The over-correction. Retrying must NOT turn silence into "busy" — a
    wedged event loop is exactly the terminal-less orphan this feature exists to
    clear, and refusing it trades one silent failure for another."""
    import urllib.request as _u
    monkeypatch.setattr(research.time, "sleep", lambda *_a: None)
    monkeypatch.setattr(_u, "urlopen",
                        lambda url, timeout=None: (_ for _ in ()).throw(OSError("dead")))
    assert research._probe_backend_activity_until_settled(8000, settle_s=5.0) is None
    assert research._backend_activity_is_work(None) is False


def test_an_explicit_idle_answer_is_not_retried(monkeypatch):
    """A real reading stops the loop whatever it says. Retrying an explicit
    `running: false` would only delay every legitimate reclaim."""
    import urllib.request as _u
    calls = {"n": 0}

    def _idle(url, timeout=None):
        calls["n"] += 1
        return _FakeResponse(
            json.dumps({"status": "ok", "running": False, "pending": 0}).encode(), 200)

    monkeypatch.setattr(_u, "urlopen", _idle)
    assert research._probe_backend_activity_until_settled(8000, settle_s=5.0) == {
        "running": False, "pending": 0}
    assert calls["n"] == 1


@pytest.fixture
def reclaim_bench(monkeypatch):
    """Drive `_reclaim_port` with a chosen holder and record every signal.

    The real function is executed — nothing here re-implements its decision.
    """
    signals: list[tuple[int, int]] = []

    def _install(*, activity, holders=None, answers_health=None, frees_after_kill=True):
        # ⚠ Default the health answer to AGREE with the activity answer. It used
        # to default True even when `activity=None`, which is an internally
        # impossible holder — nothing answered the activity probe, yet the same
        # socket answered a health probe 200. A bench that cannot represent
        # "wedged: neither answers" cannot fail on a mis-fix that gates the
        # silent-holder reclaim on a health 200, and that mis-fix deletes reclaim
        # for the exact orphan the feature exists for. Pass it explicitly to
        # build the deliberately-inconsistent holder.
        if answers_health is None:
            answers_health = activity is not None
        holders = holders if holders is not None else [
            {"pid": 4242, "name": "python", "cmd": "python research.py --serve",
             "ours": True},
        ]
        calls = {"n": 0}

        def _wait(port, max_wait_s=10.0):
            # First call is the "is it already free" probe → False (held).
            calls["n"] += 1
            return False if calls["n"] == 1 else frees_after_kill

        monkeypatch.setattr(research, "_port_holders", lambda port: holders)
        monkeypatch.setattr(research, "_wait_for_port_free", _wait)
        monkeypatch.setattr(research, "_port_backend_activity", lambda port, **kw: activity)
        monkeypatch.setattr(research, "_port_answers_health",
                            lambda port, timeout=1.5: answers_health)
        monkeypatch.setattr(research.os, "kill",
                            lambda pid, sig: signals.append((pid, sig)))
        return signals

    return _install


def test_a_working_backend_is_refused_and_never_signalled(reclaim_bench):
    """⭐ THE FINDING. A holder mid-run is named, not stopped."""
    signals = reclaim_bench(activity={"running": True, "pending": 0})
    state, holders = research._reclaim_port(8000, settle_s=0.01)
    assert state == "busy"
    assert signals == [], "a backend running a pipeline was signalled"
    assert holders[0]["activity"] == {"running": True, "pending": 0}


def test_the_reclaim_ITSELF_retries_a_quiet_holder(monkeypatch):
    """⭐ THE WIRING, found by a surviving mutant. Every test above drives the
    retrying probe DIRECTLY, so reverting `_reclaim_port` to a single-shot probe
    left all of them green — the helper still exists and still passes.

    Third instance of one pattern in this wave, after the probe's URL and the
    install verdict's comparator: a helper is pinned and its CALLER is not. Here
    the whole point of the helper is that the caller uses it, so this drives the
    real `_reclaim_port` against a holder that only answers on the third ask."""
    import urllib.request as _u
    signals: list = []
    calls = {"n": 0}

    def _slow_to_answer(url, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:                       # blocked event loop, twice
            raise OSError("timed out")
        return _FakeResponse(
            json.dumps({"status": "ok", "running": True, "pending": 0}).encode(), 200)

    monkeypatch.setattr(research.time, "sleep", lambda *_a: None)
    monkeypatch.setattr(_u, "urlopen", _slow_to_answer)
    monkeypatch.setattr(research, "_port_holders", lambda port: [
        {"pid": 4242, "name": "python", "cmd": "python research.py --serve", "ours": True}])
    _probe = {"n": 0}

    def _wait(port, max_wait_s=10.0):
        _probe["n"] += 1
        return _probe["n"] != 1                  # held on the first ask
    monkeypatch.setattr(research, "_wait_for_port_free", _wait)
    monkeypatch.setattr(research.os, "kill", lambda pid, sig: signals.append((pid, sig)))

    state, _holders = research._reclaim_port(8000, settle_s=5.0)

    assert state == "busy", (
        "the reclaim asked once and read a briefly-blocked worker as idle — a "
        "run three hours in is signalled for one slow moment")
    assert signals == [], "a working backend was signalled"


def test_a_backend_with_queued_work_is_refused_too(reclaim_bench):
    signals = reclaim_bench(activity={"running": False, "pending": 1})
    state, _ = research._reclaim_port(8000, settle_s=0.01)
    assert state == "busy"
    assert signals == []


def test_an_idle_holder_is_still_reclaimed(reclaim_bench):
    """⛔ OVER-CORRECTION GUARD. Clearing the terminal-less orphan is the whole
    reason this path exists; a guard that refuses it deletes the feature."""
    signals = reclaim_bench(activity={"running": False, "pending": 0})
    state, _ = research._reclaim_port(8000, settle_s=0.01)
    assert state == "reclaimed"
    assert [pid for pid, _ in signals] == [4242]


def test_a_holder_that_does_not_answer_at_all_is_still_reclaimed(reclaim_bench):
    """⛔ OVER-CORRECTION GUARD. A wedged event loop is exactly the state the
    abandoned backend is in — refusing on silence puts us back at the
    unexplained EADDRINUSE this replaced."""
    signals = reclaim_bench(activity=None)
    state, _ = research._reclaim_port(8000, settle_s=0.01)
    assert state == "reclaimed"
    assert [pid for pid, _ in signals] == [4242]


def test_the_health_STATUS_probe_is_not_what_gates_the_reclaim(reclaim_bench):
    """⛔ THE REVIEW'S LITERAL SUGGESTION, PINNED AS NOT TAKEN.

    `/api/health` returns ok on every path it can reach, so the orphan we are
    trying to clear answers 200 too. Gating on `_port_answers_health` would
    refuse EVERY reclaim while reading like a safety fix. Health says yes here
    and the idle holder is still reclaimed."""
    signals = reclaim_bench(activity={"running": False, "pending": 0},
                            answers_health=True)
    state, _ = research._reclaim_port(8000, settle_s=0.01)
    assert state == "reclaimed"
    assert signals, "reclaim was gated on the liveness probe"


def test_a_foreign_holder_still_outranks_the_busy_check(reclaim_bench):
    """Identity is decided before activity: something that is not ours is
    refused without ever being asked what it is doing."""
    reclaim_bench(activity={"running": True, "pending": 0},
                  holders=[{"pid": 7, "name": "nginx", "cmd": "nginx", "ours": False}])
    state, holders = research._reclaim_port(8000, settle_s=0.01)
    assert state == "foreign"
    assert "activity" not in holders[0]


def test_the_health_body_carries_the_two_fields_the_guard_reads():
    """The guard is only as true as the endpoint. If `/api/health` ever stops
    publishing `running`/`pending`, `_port_backend_activity` degrades to "not
    working" and the blocker comes back silently — so pin the contract at the
    producer, not just at the consumer."""
    src = inspect.getsource(research)
    start = src.index('@app.get("/api/health")')
    body = src[start:start + 1600]
    assert '"running": bool(_QUEUE_STATE.get("running"))' in body
    assert '"pending": _job_queue.qsize()' in body


def _serve_boot_fn_source() -> str:
    """The source of the function that calls `_reclaim_port`."""
    src = pathlib.Path(research.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seg = ast.get_source_segment(src, node) or ""
            if "_reclaim_port" in seg and "SystemExit" in seg:
                return seg
    raise AssertionError("no function calls _reclaim_port and refuses")


def test_the_busy_verdict_refuses_the_bind_instead_of_falling_through():
    """A new state the caller does not handle would fall straight through to
    uvicorn and bind-fail with the raw errno — the exact failure `_reclaim_port`
    was written to end. Asserted on the parsed branch, not on its text."""
    fn_src = _serve_boot_fn_source()
    tree = ast.parse(textwrap_dedent(fn_src))
    handled = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (isinstance(test, ast.Compare)
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value == "busy"):
            continue
        for stmt in ast.walk(node):
            if (isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call)
                    and getattr(stmt.exc.func, "id", "") == "SystemExit"
                    and stmt.exc.args
                    and getattr(stmt.exc.args[0], "value", None) == 3):
                handled = True
    assert handled, "the 'busy' verdict does not refuse the bind"


def textwrap_dedent(s: str) -> str:
    import textwrap

    return textwrap.dedent(s)


# ══════════════════════════════════════════════════════════════════════════
# Finding 2 — a billing chip is not a model
# ══════════════════════════════════════════════════════════════════════════


UPSELL_CORPUS = [
    # (label, is an upsell for "opus")
    ("Upgrade to Opus", True),
    ("Get Opus with Max", True),
    ("Upgrade to Opus 5.2", True),          # ⭐ versioned — competes on rank
    ("Subscribe to unlock Opus", True),
    # ⭐ "unlock" was MISSING from the shared verb list while three other guards
    # in research.py already treated it as one, so this chip parsed a version
    # and outranked every genuine row. The corpus row above hid it: that one is
    # caught by "subscribe", so nothing here exercised "unlock" alone.
    ("Unlock Opus 5.2", True),
    ("Unlock Opus with Max", True),
    ("Try Opus", True),
    ("UPGRADE TO OPUS", True),
    ("Upgrade\n  to\n  Opus", True),        # collapsed before the window is measured
    # ⭐ Only collapsing makes this an upsell: 30 raw spaces put the family word
    # outside the window, one space puts it inside. A row rendered across lines
    # must not read differently from the same row rendered inline.
    ("Upgrade to" + " " * 30 + "Opus", True),
    ("Opus 5", False),
    ("Opus", False),
    ("Opus 5 Max", False),
    ("Sonnet 4.6", False),
    # A blurb verb, far from the family word: a bare verb test would bin this
    # genuine row and empty the menu.
    ("Opus 4.5 — try our most capable model", False),
    # Family first, sales tail: this row IS the model.
    ("Opus 5 — upgrade for more usage", False),
    # ⭐⭐ THE ACCEPTED RESIDUAL, pinned so nobody "fixes" it back. A "family
    # named first" exemption was written on 2026-08-14 to keep these three
    # selectable, and reverted the same day: driven through the shipped picker,
    # the third one was CLICKED and returned as a confirmed pick at version 5,
    # beating a genuine Opus 4.5 row — a billing surface plus a false success,
    # which is the blocking finding this file exists for.
    #
    # So these are excluded, deliberately. Excluding costs a downgrade to a
    # model that still works; including costs a modal over the composer and a
    # run reporting success into it. Claude's observed row copy does not
    # re-name the family, so the cost is unattested and the benefit is the
    # shipped defect.
    ("Opus 5 — try Opus with extended thinking", True),
    ("Opus 5 — get the most out of Opus", True),
    ("Opus 5 · Upgrade to Opus Max for more usage", True),
    # ⚠⚠ ASTRAL CHARACTERS, added 2026-08-24 by cross-verification. The 24-char
    # window is counted in CODE POINTS here and in UTF-16 CODE UNITS in every JS
    # port, so each emoji between the verb and the noun costs 1 on this side and
    # 2 on that one. Below the divergence threshold both agree, and that is the
    # point of pinning it: the anti-drift test drives BOTH implementations over
    # this row, so the day the counting rule changes on either side it says so
    # rather than the browser quietly reading a sales row as a model.
    ("Upgrade \U0001F680\U0001F680 to Opus", True),
    ("Upgrade to Opus \U0001F680\U0001F680 5", True),
    # ⭐ Whitespace parity with the JS port, both directions. Python's
    # `str.isspace()` and JS's `\s` disagree on these two classes, and the window
    # is counted in CHARACTERS — so before `_collapse_ws` existed, each of these
    # was an upsell to one implementation and a model row to the other.
    ("Get" + "\x1c" * 30 + "Opus 9.9", True),      # Python-only whitespace
    ("Get" + "\ufeff" * 30 + "Opus 9.9", True),  # JS-only whitespace (a BOM)
    # The verb is not a whole word.
    ("Regetopus", False),
    # Too far apart to be the verb's object.
    ("Upgrade your plan for faster answers on every model — Opus included", False),
]


@pytest.mark.parametrize("label,expected", UPSELL_CORPUS)
def test_is_upsell_corpus(label, expected):
    assert models.is_upsell(label, "opus") is expected


def test_a_versioned_upsell_outranks_every_real_row_without_the_guard():
    """⭐ Why this is wider than "a fresh device with no known-good". The chip
    parses a version, so it competes on RANK — and wins."""
    labels = ["Opus 5", "Upgrade to Opus 5.2", "Sonnet 4.6"]
    unguarded = models.pick_highest_model(labels, "opus")
    assert unguarded["label"] == "Upgrade to Opus 5.2"
    guarded = models.pick_highest_model(labels, "opus", drop_upsell=True)
    assert guarded["label"] == "Opus 5"


def test_a_menu_offering_only_a_chip_selects_nothing():
    assert models.pick_highest_model(
        ["Upgrade to Opus", "Sonnet 4.6"], "opus", drop_upsell=True) is None


def test_the_python_mirror_keeps_a_versionless_family_row():
    """⛔ OVER-CORRECTION GUARD, python half."""
    got = models.pick_highest_model(["Opus", "Sonnet 4.6"], "opus", drop_upsell=True)
    assert got["label"] == "Opus" and got["version"] is None


def test_the_upsell_drop_is_opt_in_so_the_unported_ranker_still_mirrors():
    """The Gemini ranker has not ported this rule. A default-on exclusion would
    put this function's answer at odds with that browser path — which is how the
    reject rule drifted the first time."""
    sig = inspect.signature(models.pick_highest_model)
    assert sig.parameters["drop_upsell"].default is False


def test_production_hands_the_browser_the_real_verb_list():
    """⭐ The rule can be perfect and still never run. Every browser test here
    passes `verbs` explicitly, so an empty list in the PRODUCTION args would
    leave all of them green while the live picker excluded nothing. Asserted on
    the parsed argument dicts, so it also fails if either one is built from a
    literal list that drifts from `UPSELL_VERBS`."""
    src = pathlib.Path(research.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    seen = {}
    rebinds = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        for name in names:
            if name not in ("_pick_args", "_probe_args"):
                continue
            entries = {}
            spread_self = False
            for k, v in zip(node.value.keys, node.value.values):
                if k is None:
                    # `_pick_args = {**_pick_args, "fam": …}` — the plan-limit
                    # fallback re-aims the SAME dict at another family and
                    # INHERITS everything else, verbs included. Re-deriving it
                    # here would let the two copies drift, so a self-spread is
                    # the correct shape and must not overwrite the base entry
                    # this test is checking.
                    spread_self = spread_self or (isinstance(v, ast.Name) and v.id == name)
                elif isinstance(k, ast.Constant):
                    entries[k.value] = v
            if spread_self:
                # …but it may NOT quietly re-bind the two keys that carry the
                # sales-verb rule into the browser. A spread that overrode them
                # with a literal would inherit this test's blessing while
                # handing the picker a different rule — the exact drift the
                # whole assertion exists to catch, wearing the shape that is
                # allowed.
                for key in ("verbs", "upsellWindow"):
                    if key in entries:
                        rebinds.append(f"{name} (line {node.lineno}) re-binds {key!r}")
                continue
            seen[name] = entries

    assert not rebinds, (
        "a spread-built argument dict overrides the shared verb policy:\n  "
        + "\n  ".join(rebinds))
    assert set(seen) == {"_pick_args", "_probe_args"}, (
        f"could not find both argument dicts, saw {sorted(seen)}")

    def _reads(node, const_name):
        """`UPSELL_VERBS` or `list(UPSELL_VERBS)`, and nothing else."""
        if isinstance(node, ast.Name):
            return node.id == const_name
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "list":
            return bool(node.args) and getattr(node.args[0], "id", "") == const_name
        return False

    for name, entries in seen.items():
        assert "verbs" in entries, f"{name} does not pass the verb list at all"
        assert _reads(entries["verbs"], "UPSELL_VERBS"), (
            f"{name} passes something other than models.UPSELL_VERBS")
        assert _reads(entries["upsellWindow"], "UPSELL_WINDOW"), (
            f"{name} passes something other than models.UPSELL_WINDOW")

    # ⚠ AND THE DICTS HAVE TO BE THE ONES ACTUALLY HANDED OVER. Asserting on the
    # assignments alone leaves the wiring unchecked: an edit that passes a
    # different inline dict while leaving these two standing keeps this green,
    # and the JS defaults `verbs || []` — so the live picker would exclude
    # nothing while every browser test, which passes `verbs` explicitly, stays
    # green. Two halves, both required.
    def _carries_checked_args(node) -> str:
        """The checked dict this argument expression is built from, or ""."""
        if isinstance(node, ast.Name) and node.id in seen:
            return node.id
        # `{**_pick_args, "pin": …}` — the Step 1B* upgrade re-pins the target
        # and INHERITS everything else, verbs included. A spread is fine; a
        # freshly-written dict is not.
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if k is None and isinstance(v, ast.Name) and v.id in seen:
                    return v.id
        return ""

    passed = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "evaluate"
                and len(node.args) >= 2):
            js_arg = getattr(node.args[0], "id", "")
            if js_arg in ("_pick_opus_js", "_probe_opus_js"):
                passed.append((js_arg, node.lineno, _carries_checked_args(node.args[1])))

    assert any(p[0] == "_pick_opus_js" for p in passed), "the picker is never evaluated"
    assert any(p[0] == "_probe_opus_js" for p in passed), "the probe is never evaluated"
    stray = [(js, ln) for js, ln, src in passed if not src]
    assert not stray, (
        f"a picker/probe evaluate builds its own argument dict at line(s) "
        f"{stray} — the JS defaults `verbs || []`, so that call excludes nothing "
        f"while every browser test, which passes verbs explicitly, stays green")


def test_the_verb_list_has_exactly_one_definition():
    """Three surfaces read these words: `is_upsell`, the ChatGPT tier picker,
    and the CUA mission rendered from the policy key."""
    assert models.P1_MODEL_POLICY["chatgpt"]["upgrade_verbs"] is models.UPSELL_VERBS
    assert models.p1_words("chatgpt", "upgrade_verbs") == list(models.UPSELL_VERBS)


# ── the same rule, executed in the browser ───────────────────────────────

pytestmark_node = pytest.mark.skipif(NODE is None, reason="node is required")


def _rows(labels):
    return [el("div", {"role": "menuitem", "w": "300", "h": "40"}, text=t)
            for t in labels]


def _menu(*labels):
    """A MOUNTED model popover whose rows carry `labels`.

    ⚠ Wrapped in a page root deliberately: the shim's outermost node is not
    returned by `document.querySelectorAll`, so an unwrapped `[role=menu]` is
    invisible to the picker and it silently falls through to its `document.body`
    fallback — which passes these assertions for the wrong reason. `_bare` below
    exercises that fallback on purpose."""
    return el("div", {"id": "page", "w": "1200", "h": "900"},
              kids=[el("div", {"role": "menu", "w": "320", "h": "400"},
                       kids=_rows(labels))])


def _bare(*labels):
    """The same rows with NO mounted menu — the body fallback, which is where a
    billing chip most plausibly sits (the review's "a menu read mid-render")."""
    return el("div", {"id": "page", "w": "1200", "h": "900"}, kids=_rows(labels))


def _pick(spec, **args):
    js = js_constant(research.setup_claude_dr, "_pick_opus_js")
    arg = {"pin": None, "below": None, "fam": "opus", "triggerText": "",
           "verbs": list(models.UPSELL_VERBS), "upsellWindow": models.UPSELL_WINDOW}
    arg.update(args)
    return run_js(spec, js, arg)


@pytestmark_node
def test_the_browser_picks_the_real_row_over_a_versioned_chip():
    """⭐ THE FINDING, run through the shipped JS rather than asserted about."""
    out = _pick(_menu("Upgrade to Opus 5.2", "Opus 5", "Sonnet 4.6"))
    assert out["ret"]["label"] == "Opus 5"
    assert out["clicks"] == ["Opus 5"]


@pytestmark_node
def test_the_browser_refuses_a_chip_even_when_a_pin_is_held():
    """The chip parses, so it reaches the pin branch too — this is the half the
    first triage missed by calling the defect fresh-device-only."""
    out = _pick(_menu("Upgrade to Opus 5.2", "Opus 5"), pin=5.2)
    assert out["clicks"] == ["Opus 5"]


@pytestmark_node
def test_the_browser_clicks_nothing_when_the_only_match_is_a_chip():
    """Pre-fix this returned the chip's text — truthy — and the caller logged a
    successful model selection while the upsell modal covered the composer."""
    out = _pick(_menu("Upgrade to Opus", "Sonnet 4.6"))
    assert out["ret"] is None
    assert out["clicks"] == []


@pytestmark_node
def test_the_body_fallback_refuses_a_chip_too():
    """⭐ The path the review named — "a menu read mid-render". With no menu
    mounted the picker scans the whole page, which is exactly where a billing
    chip lives, and pre-fix it was the ONLY family match on that page."""
    out = _pick(_bare("Upgrade to Opus", "Sonnet 4.6"))
    assert out["ret"] is None
    assert out["clicks"] == []


@pytestmark_node
def test_the_body_fallback_still_finds_a_real_row():
    """⛔ OVER-CORRECTION GUARD for the case above."""
    out = _pick(_bare("Upgrade to Opus", "Opus 5"))
    assert out["clicks"] == ["Opus 5"]


@pytestmark_node
def test_a_versionless_family_row_is_still_picked():
    """⛔ OVER-CORRECTION GUARD, browser half. The review's second suggestion —
    "require v !== null before treating a click as a confirmed selection" — is
    NOT taken, because a version-less rename is exactly the day the menu must
    not go empty."""
    out = _pick(_menu("Opus", "Sonnet 4.6"))
    assert out["ret"]["label"] == "Opus"
    assert out["ret"]["version"] is None
    assert out["clicks"] == ["Opus"]


@pytestmark_node
def test_a_genuine_row_whose_blurb_carries_a_verb_is_still_picked():
    """⛔ OVER-CORRECTION GUARD. Row text is title+description concatenated, so
    a bare verb rule would bin this and select nothing."""
    out = _pick(_menu("Opus 4.5 — try our most capable model"))
    assert out["clicks"] == ["Opus 4.5 — try our most capable model"]


@pytestmark_node
def test_the_probe_does_not_report_a_chip_as_the_highest_offered():
    """Without this the two disagree in the one direction that costs a run every
    time: the probe reads 5.2 as offered, the picker refuses to click it, and
    "offered but not clickable" is logged forever."""
    js = js_constant(research.setup_claude_dr, "_probe_opus_js")
    arg = {"fam": "opus", "verbs": list(models.UPSELL_VERBS),
           "upsellWindow": models.UPSELL_WINDOW}
    out = run_js(_menu("Upgrade to Opus 5.2", "Opus 5"), js, arg)
    assert out["ret"]["highest"] == 5.0


# Only the family-bearing rows: a label that does not name the family is refused
# for a different reason entirely, so it would certify nothing about the upsell
# rule in either direction.
_FAMILY_CORPUS = [(t, up) for t, up in UPSELL_CORPUS if "opus" in t.lower()]


@pytestmark_node
@pytest.mark.parametrize("label,expected", _FAMILY_CORPUS)
def test_the_js_port_and_the_python_definition_agree(label, expected):
    """⭐ THE ANTI-DRIFT TEST. The same corpus through both implementations. A
    mirror that is never executed against its twin is how these two diverged
    before — the JS used `includes()` while the python used word boundaries, and
    the unit suite certified semantics the browser never ran."""
    # A row dropped as an upsell is never clicked; one that is not, is the only
    # family row present, so it wins.
    out = _pick(_menu(label))
    clicked = bool(out["clicks"])
    assert clicked is (not expected), (
        f"browser {'clicked' if clicked else 'refused'} {label!r} but "
        f"models.is_upsell says upsell={expected}")


@pytestmark_node
@pytest.mark.parametrize("label,expected", _FAMILY_CORPUS)
def test_the_PROBE_reads_the_corpus_the_same_way_the_picker_does(label, expected):
    """⛔⛔ FOUND BY MUTATION 2026-08-23, and it is the reason the mutants were
    deliberately spread across the copies.

    This filter now exists FOUR times in research.py — the picker, this probe,
    the dropdown-click path and the Gemini ranker wave 6 ported it to. Every
    corpus test above drives the PICKER. The probe had exactly one label,
    "Upgrade to Opus 5.2", whose verb and family word sit four characters
    apart — so unbounding the proximity window changed nothing it asserted, and
    a mutant that binned every genuine row survived against a green suite.

    The two are byte-identical and MUST agree: the probe deciding a row is an
    upsell while the picker does not is precisely the "offered but not
    clickable" loop this file was written to close, in reverse."""
    out = _probe(_menu(label))
    if expected:
        # An upsell row raises neither the count nor the version, and IS counted
        # as a chip — which is the signal that tells a plan limit apart from a
        # rename. Every upsell row can be judged this way, versioned or not.
        assert out["n"] == 0, (
            f"the probe counted {label!r} as an offered model but "
            f"models.is_upsell says it is an upsell")
        assert out["chips"] >= 1, f"{label!r} was dropped without being counted as a chip"
        return
    # ⚠ THE OTHER HALF NEEDS A VERSION, and the first draft of this test did
    # not — it failed on "Opus", "Regetopus" and the plan-upsell row, all of
    # which the probe drops for having no version to RANK rather than for being
    # upsells. That is a different exclusion and asserting it here would have
    # pinned the wrong mechanism. The picker's corpus test does not hit this
    # because it measures a CLICK, which needs no version.
    if not any(c.isdigit() for c in label):
        assert out["chips"] == 0, (
            f"the probe treated {label!r} as a sales chip — it has no version, "
            f"so it should be dropped as unrankable, not excluded as an upsell")
        return
    assert out["n"] >= 1, (
        f"the probe excluded {label!r} but models.is_upsell says it is a "
        f"genuine row — this is 'offered but not clickable' in reverse")


def test_the_corpus_covers_both_verdicts_in_the_browser():
    """A filter that accidentally emptied one side of `_FAMILY_CORPUS` would
    leave the agreement test passing while checking one polarity."""
    assert sum(1 for _t, up in _FAMILY_CORPUS if up) >= 5
    assert sum(1 for _t, up in _FAMILY_CORPUS if not up) >= 4


def _inline_evaluate_js(fn, marker: str) -> str:
    """The JS of a `page.evaluate(\"\"\"…\"\"\", …)` written INLINE inside `fn`.

    ⚠ `js_constant` cannot reach these — it resolves NAMED assignments only —
    which is exactly why the popover OPENER had no test at all while the picker
    it feeds had a dozen. An un-extractable script is an untested one.
    """
    import textwrap
    src = textwrap.dedent(inspect.getsource(fn))
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "evaluate"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and marker in node.args[0].value):
            return node.args[0].value
    raise AssertionError(
        f"no inline page.evaluate in {fn.__name__} contains {marker!r}")


def _open_popover(spec):
    """Run the SHIPPED Step 1A opener against `spec`."""
    js = _inline_evaluate_js(research.setup_claude_dr, "The model-selector trigger")
    return run_js(spec, js, {"fam": "opus", "verbs": list(models.UPSELL_VERBS),
                             "upsellWindow": models.UPSELL_WINDOW})


@pytestmark_node
def test_the_popover_opener_does_not_press_a_billing_banner():
    """⭐ The opener takes the FIRST visible button naming the family, in
    document order — and an "Upgrade to Opus" banner above the composer names it
    exactly the way the trigger does.

    ⓘ Not the blocking finding: the pick that follows finds only excluded chips,
    gives up and Escapes, so nothing is ever REPORTED as a successful selection.
    But the user gets a payment modal in the middle of a run, and the guard was
    already sitting one function away."""
    page = el("div", {"id": "page", "w": "1200", "h": "900"}, kids=[
        el("button", {"w": "260", "h": "40"}, text="Upgrade to Opus with Max"),
        el("button", {"w": "180", "h": "36"}, text="Opus 5"),
    ])
    out = _open_popover(page)
    assert out["ret"] is True, "the opener found nothing to press"
    assert out["clicks"] == ["Opus 5"], (
        f"the opener pressed {out['clicks']!r} — a billing surface opens over "
        f"the composer for the rest of the run"
    )


@pytestmark_node
def test_the_opener_still_finds_the_trigger_when_no_banner_is_present():
    """⛔ Over-correction: a filter that ate the trigger too would leave Step 1A
    unable to open the menu at all, which is a total P2 outage rather than a
    modal.

    ⭐ It cannot eat the button that established `model_ok`, and that is
    structural rather than lucky: the trigger READ already refuses every button
    matching its own verb pattern, so a confirmed model verdict can only have
    come from a verb-free button — and `isUpsell` needs a verb."""
    page = el("div", {"id": "page", "w": "1200", "h": "900"}, kids=[
        el("button", {"w": "180", "h": "36"}, text="Opus 5"),
    ])
    out = _open_popover(page)
    assert out["ret"] is True and out["clicks"] == ["Opus 5"]


@pytestmark_node
def test_the_opener_still_falls_back_to_a_sibling_model_name():
    """The second leg — a trigger reading `Sonnet 4.6` is still the model
    selector, and must remain pressable."""
    page = el("div", {"id": "page", "w": "1200", "h": "900"}, kids=[
        el("button", {"w": "180", "h": "36"}, text="Sonnet 4.6"),
    ])
    out = _open_popover(page)
    assert out["ret"] is True and out["clicks"] == ["Sonnet 4.6"]


@pytestmark_node
def test_a_family_first_sales_row_is_refused_even_though_it_outranks_the_real_one():
    """⭐⭐ THE REGRESSION A "FAMILY NAMED FIRST" EXEMPTION CAUSED, kept as the
    reason it is not coming back.

    That exemption was written on 2026-08-14 so a genuine row whose blurb reads
    verb-then-family would stay selectable, and it was reverted the same day
    because THIS menu — driven through the shipped picker, not argued about —
    clicked the sales row and returned it as a confirmed pick at version 5,
    beating the real Opus 4.5. A billing surface over the composer, a false
    success in the log, and a poisoned version feeding the known-good machinery:
    the blocking finding, restored.

    The concern the exemption answered was hypothetical. This was reproduced."""
    out = _pick(_menu("Opus 5 · Upgrade to Opus Max for more usage",
                      "Opus 4.5", "Sonnet 4.6"))
    assert out["clicks"] == ["Opus 4.5"], (
        f"the picker took {out['clicks']!r} — a sales row that names the family "
        f"before the verb is still a sales row, and it outranks every real one"
    )


@pytestmark_node
def test_the_cost_of_that_decision_is_pinned_too():
    """⚠ The other side of the same trade, stated rather than hidden: a GENUINE
    row whose description re-names the family after a sales verb is excluded,
    and a lower row is taken instead.

    That is a downgrade to a model that still works, against a modal over the
    composer and a run reporting success into it. Claude's observed row copy
    ("Our most capable model") does not re-name the family, so this cost is
    unattested while the failure it buys off is the shipped one. Pinned so the
    trade is a decision on the record rather than something rediscovered."""
    out = _pick(_menu("Opus 5 — try Opus with extended thinking", "Opus 4.5"))
    assert out["clicks"] == ["Opus 4.5"]


@pytestmark_node
def test_a_row_with_a_sales_tail_that_does_not_rename_the_family_is_still_picked():
    """The boundary that keeps the residual narrow. "Opus 5 — upgrade for more
    usage" IS the model with a sales tail: no family word follows the verb, so
    nothing here reads as selling the family, and it stays selectable."""
    out = _pick(_menu("Opus 5 — upgrade for more usage", "Sonnet 4.6"))
    assert out["clicks"] == ["Opus 5 — upgrade for more usage"]


@pytestmark_node
@pytest.mark.parametrize("pad,who", [("\x1c", "Python"), ("\ufeff", "JS")])
def test_the_two_ports_collapse_the_same_whitespace(pad, who):
    """⭐ Each of these characters is whitespace to exactly ONE of the two
    languages, and the upsell window is counted in CHARACTERS on the collapsed
    string — so before the shared set existed, a chip padded with 30 of them was
    a sales prompt to one implementation and a model row to the other. Measured
    on the real ported code, which is how a "character-for-character port"
    turned out not to be one."""
    label = "Get" + pad * 30 + "Opus 9.9"
    assert models.is_upsell(label, "opus") is True
    out = _pick(_menu(label))
    assert out["clicks"] == [], (
        f"{who}-only whitespace: the browser clicked a chip the mirror excludes"
    )


# ══════════════════════════════════════════════════════════════════════════
# Finding 3 — a refusal must not lower `needsRestart`
# ══════════════════════════════════════════════════════════════════════════


class _FakeDoc:
    def __init__(self, db):
        self._db = db

    def update(self, payload):
        self._db.writes.append(payload)
        # Applied with REAL Firestore semantics, so `doc` below shows what the
        # device document would actually hold — the only level at which
        # "the flag survived" is a claim about production rather than about a
        # payload shape.
        apply_firestore_update(self._db.doc, payload)


class _FakeCollection:
    def __init__(self, db):
        self._db = db

    def document(self, _id):
        return _FakeDoc(self._db)


class _FakeDb:
    def __init__(self, doc=None):
        self.writes: list[dict] = []
        self.doc: dict = dict(doc or {})

    def collection(self, _name):
        return _FakeCollection(self)


@pytest.fixture
def fake_db(monkeypatch):
    def _make(doc=None):
        db = _FakeDb(doc)
        monkeypatch.setattr(research, "_firebase_db", db)
        return db

    db = _make()
    db.remake = _make
    return db


def test_an_outcome_replaces_the_whole_map(fake_db):
    """The default is unchanged: a caller carrying the whole verdict must not
    leave a previous attempt's journal underneath it."""
    assert research._write_update_status("d1", {"state": "installed",
                                                "needsRestart": True}) is True
    (payload,) = fake_db.writes
    assert set(payload) == {"updateStatus"}
    assert payload["updateStatus"]["state"] == "installed"
    assert isinstance(payload["updateStatus"]["at"], int)


def test_a_refusal_writes_dotted_paths_so_untouched_keys_survive(fake_db):
    """⭐ THE FINDING. A nested map value REPLACES the map; dotted paths merge
    into it, so `needsRestart` is not deleted by a write that never mentions
    it."""
    research._write_update_status(
        "d1", {"state": "deferred", "reason": "a research run is in progress"},
        merge=True)
    (payload,) = fake_db.writes
    assert set(payload) == {"updateStatus.state", "updateStatus.reason",
                            "updateStatus.at"}
    assert "updateStatus" not in payload, "still replacing the whole map"
    assert "updateStatus.needsRestart" not in payload, "a refusal must not set it"


@pytest.mark.parametrize(
    "state,reason",
    [("deferred", "a research run is in progress"),
     ("failed", "not the device owner"),
     ("failed", "not supervised — restart it on the machine"),
     ("failed", "could not verify device ownership")],
)
def test_a_refusal_leaves_a_pending_restart_standing(fake_db, state, reason):
    """⭐ THE FINDING, AS THE DEVICE DOCUMENT SEES IT — not as a payload shape.

    The device is mid-way through an update whose files landed and whose restart
    leg did not, which is the one state the fallback Restart button exists for.
    Every refusal answers the tap, and none of them may lower the flag. The
    identity refusals matter most: they fire for a SHARER, and the flag they were
    erasing belonged to the owner."""
    db = fake_db.remake({"updateStatus": {
        "state": "installed", "latest": "0.1.34", "current": "0.1.33",
        "needsRestart": True, "at": 1}})
    research._write_update_status("d1", {"state": state, "current": "0.1.33",
                                         "reason": reason}, merge=True)
    after = db.doc["updateStatus"]
    assert after["needsRestart"] is True, "the refusal deleted the Restart flag"
    assert after["latest"] == "0.1.34", "the refusal wiped the target version"
    assert after["state"] == state and after["reason"] == reason
    assert after["at"] != 1, "the refusal did not refresh the stamp"


def test_the_same_refusal_written_the_old_way_destroys_it(fake_db):
    """The counterfactual, so the test above cannot pass for a trivial reason.
    Identical payload, `merge` left at its default: the flag is gone."""
    db = fake_db.remake({"updateStatus": {
        "state": "installed", "latest": "0.1.34", "needsRestart": True, "at": 1}})
    research._write_update_status("d1", {"state": "deferred", "current": "0.1.33",
                                         "reason": "a research run is in progress"})
    after = db.doc["updateStatus"]
    assert "needsRestart" not in after and "latest" not in after


def test_an_outcome_may_still_lower_the_flag(fake_db):
    """⛔ OVER-CORRECTION GUARD. "A refusal must never lower needsRestart" is not
    "nothing may". The update path publishing a completed verdict has to be able
    to clear it, or the button outlives the restart that satisfied it."""
    db = fake_db.remake({"updateStatus": {"state": "installed",
                                          "needsRestart": True, "at": 1}})
    research._write_update_status("d1", {"state": "installed", "current": "0.1.34",
                                         "latest": "0.1.34", "needsRestart": False,
                                         "reason": ""})
    assert db.doc["updateStatus"]["needsRestart"] is False


def test_a_failed_write_is_reported_not_raised(fake_db, monkeypatch):
    def _boom(_name):
        raise RuntimeError("rules")

    monkeypatch.setattr(fake_db, "collection", _boom)
    assert research._write_update_status("d1", {"state": "failed"}, merge=True) is False


def _write_status_calls():
    """Every `_write_update_status(...)` call in research.py, as (state, kwargs,
    keys) triples, read off the parse tree."""
    src = pathlib.Path(research.__file__).read_text(encoding="utf-8")
    out = []
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "_write_update_status"):
            continue
        if len(node.args) < 2:
            continue
        if not isinstance(node.args[1], ast.Dict):
            # ⛔ NOT `continue`. Skipping the payloads this scan cannot read is
            # what turned the invariant below into a formality: a refusal branch
            # written the natural way — build `payload = {...}` on one line, pass
            # the NAME on the next — became invisible, and could replace the
            # whole map and null `latest` with the guard still green. Anything
            # unreadable is now a failure of THIS test, not a silent exemption.
            out.append(("<unreadable payload>", False, ["latest"], node.lineno))
            continue
        keys = [k.value for k in node.args[1].keys if isinstance(k, ast.Constant)]
        state = None
        for k, v in zip(node.args[1].keys, node.args[1].values):
            if (isinstance(k, ast.Constant) and k.value == "state"
                    and isinstance(v, ast.Constant)):
                state = v.value
        merge = any(kw.arg == "merge" and getattr(kw.value, "value", None) is True
                    for kw in node.keywords)
        out.append((state, merge, keys, node.lineno))
    return out


def test_every_refusal_call_site_merges_and_none_of_them_clears_latest():
    """⭐ The invariant, not the seven edits. A NEW refusal branch written the
    old way fails here — which is how this one got in: the sites were added one
    at a time, each copying the last."""
    calls = _write_status_calls()
    unreadable = [(s, ln) for s, _m, _k, ln in calls if s == "<unreadable payload>"]
    assert not unreadable, (
        f"a `_write_update_status` call passes a payload this scan cannot read, "
        f"at line(s) {[ln for _s, ln in unreadable]}. It may be a refusal that "
        f"replaces the whole map — inline the dict, or teach this scan to follow "
        f"the name. Do not let it pass unexamined.")
    refusals = [c for c in calls if c[0] in ("failed", "deferred")]
    assert len(refusals) >= 7, f"expected the known refusal sites, saw {len(refusals)}"
    bad_merge = [(s, ln) for s, m, _k, ln in refusals if not m]
    assert not bad_merge, f"refusals replacing the whole map: {bad_merge}"
    bad_latest = [(s, ln) for s, _m, k, ln in refusals if "latest" in k]
    assert not bad_latest, (
        f"refusals still writing `latest` — under dotted paths that sets it to "
        f"null exactly as before: {bad_latest}")


def test_a_progress_or_outcome_report_still_replaces():
    """The other half of the rule. `installing` supersedes whatever came before
    it, so it must NOT merge — a stale `needsRestart` surviving under a live
    update is the mirror-image bug."""
    installing = [c for c in _write_status_calls() if c[0] == "installing"]
    assert installing, "the in-flight progress report is gone"
    assert all(not merge for _s, merge, _k, _ln in installing)


def test_an_update_that_did_nothing_does_not_clear_the_restart_flag(monkeypatch):
    """⭐⭐ FINDING 3'S HARM THROUGH A DOOR THE WAVE DID NOT CHECK, found by a
    later cross-check rather than by the review.

    This write is not a refusal branch and did not look like one, so it kept
    replacing. But only `started` is a real transition — `already`,
    `unsupported`, `pipx not found` and the preflight `failed` all report that
    NOTHING happened, and a replace there deletes `needsRestart`.

    The sequence that bites: an update lands its files, the restart leg dies,
    the heartbeat publishes `needsRestart: true` and consumes the only sentinel.
    The user taps Update again to finish it — `_perform_self_update` reads the
    DISK version, says `already`, and the Restart button they were reaching for
    disappears while the machine keeps serving the old build. No path back
    except a manual restart: the exact dead end the wave closed everywhere else.
    """
    db = _FakeDb({"updateStatus": {"state": "installed", "needsRestart": True,
                                   "latest": "0.1.40", "at": 1}})
    monkeypatch.setattr(research, "_firebase_db", db)

    research._write_update_status(
        "dev1", {"state": "already", "current": "0.1.40", "reason": ""}, merge=True)

    doc = db.doc
    assert doc["updateStatus"]["needsRestart"] is True, (
        "a no-op update report deleted the flag the Restart button is rendered "
        "from — the user cannot finish the update from the app"
    )
    assert doc["updateStatus"]["state"] == "already"


def test_only_a_launched_upgrade_supersedes_the_whole_record():
    """The other side, pinned at the call site: `started` must still REPLACE, or
    a stale `needsRestart` survives under a live update — the mirror-image bug.
    Read off the parse tree: both arms are ordinary literal payloads, which is
    itself deliberate — a conditional expression here was rejected by the
    unreadable-payload guard above, and rightly, since a scan that cannot read a
    payload cannot certify it."""
    calls = _write_status_calls()
    started = [c for c in calls if c[0] == "started"]
    assert started, "the launched-upgrade report is gone"
    assert all(not merge for _s, merge, _k, _ln in started), (
        "a launched upgrade now MERGES — a stale needsRestart would survive "
        "under a live update, which is the mirror-image bug")
    assert all("latest" in keys for _s, _m, keys, _ln in started), (
        "the launched-upgrade report no longer carries the target version")

    # The sibling arm: state comes from `res`, so it is not a constant here.
    outcome = [c for c in calls
               if c[0] is None and c[1] and set(c[2]) == {"state", "current", "reason"}]
    assert outcome, (
        "the did-nothing outcome report is not a merge — `already`, "
        "`unsupported` and `pipx not found` would each delete needsRestart")


# ── the probe can tell a PLAN LIMIT from a RENAME ────────────────────────────

def _probe(spec):
    js = js_constant(research.setup_claude_dr, "_probe_opus_js")
    return run_js(spec, js, {"fam": "opus", "verbs": list(models.UPSELL_VERBS),
                             "upsellWindow": models.UPSELL_WINDOW})["ret"]


@pytestmark_node
def test_a_chips_only_menu_is_reported_as_chips_not_as_an_empty_menu():
    """⭐ The non-pro signal. Excluding the chips left the probe saying "no Opus
    rows" — which is the SAME answer it gives when the family was renamed or the
    menu was read mid-render, and those want opposite responses: one is a
    permanent fact about the account, the other is a transient to keep retrying.

    Counted here rather than inferred by the caller because only this loop sees
    which rows were dropped and why."""
    out = _probe(_menu("Upgrade to Opus", "Get Opus with Max", "Sonnet 4.6"))
    assert out["menu"] is True
    assert out["n"] == 0, "a chip was counted as an offered model"
    assert out["chips"] >= 1, (
        "the menu offered Opus only as a sales prompt and the probe could not "
        "say so — indistinguishable from a rename")


@pytestmark_node
def test_a_real_menu_reports_no_chips():
    """⛔ Over-correction: a chip count that fires on an ordinary menu would send
    a PRO account down the plan-limited path."""
    out = _probe(_menu("Opus 5", "Opus 4.5", "Sonnet 4.6"))
    assert out["chips"] == 0 and out["n"] == 2 and out["highest"] == 5.0


@pytestmark_node
def test_a_menu_without_the_family_at_all_is_not_read_as_plan_limited():
    """The third case, and the one that must NOT be confused with a plan limit —
    a rename or a mid-render read has no chips either."""
    out = _probe(_menu("Sonnet 4.6", "Haiku 3.5"))
    assert out["n"] == 0 and out["chips"] == 0


@pytestmark_node
def test_one_chip_is_counted_once_not_once_per_ancestor():
    """The item walk includes div/span, so a chip appears at several depths. A
    naive count reads five chips for one — which would not change the verdict
    today, but it is the kind of number someone later reasons about ("only one
    chip, probably a stray")."""
    row = el("div", {"role": "menuitem", "w": "300", "h": "40"},
             kids=[el("span", {"w": "280", "h": "20"}, text="Upgrade to Opus")])
    page = el("div", {"id": "page", "w": "1200", "h": "900"},
              kids=[el("div", {"role": "menu", "w": "320", "h": "400"}, kids=[row])])
    assert _probe(page)["chips"] == 1
