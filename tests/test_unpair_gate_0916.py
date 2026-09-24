"""Wave 9 — `--unpair` refuses when the server did not CONFIRM.

⛔⛔ THE TRIGGER IS "THE SERVER DID NOT CONFIRM", NOT "THE SERVER REFUSED". The
old code minted an ID token, POSTed /api/devices/unpair-self, and on a non-200
logged a WARN and carried on wiping — which destroyed the keystore, the only
credential that could ever ask again, while the device document and its Firebase
login stayed on the server, listed on nobody's screen and unreachable from this
machine. Worse, the COMMONEST failure made no noise at all: `if _id_token:` had
no `else`, so a failed mint issued no request, produced no status and raised no
exception. A guard written against the response would never have fired on it.
That is why the first test here is the un-minted token and not the 401.

⛔ CONFIRMATION IS TWO ANSWERS, AND ONE OF THEM IS A 404. HTTP 200 confirms, and
so does HTTP 404 whose BODY says `device_not_found` — the route's own
already-gone answer (its `device_not_found` 404 in
dg-research/src/app/api/devices/unpair-self/route.ts),
where there is nothing left to strand. A 404 from a proxy or an edge, which is
what a wrong FE_BASE_URL produces, carries no such body and must NOT confirm.
The discrimination is on the body, never on the bare status.

⛔ "NOTHING CHANGED" HAD TO BE MADE TRUE, NOT JUST PRINTED. Two things used to
run before the old POST and would have made that sentence a lie: the Firestore
sweep, which stamps 'Cancelled by Unpair' across the owner's AND every sharer's
runs (moved behind the gate), and `_fresh_user_mode_id_token()`, which is not
read-only on failure — on a genuine revoke it wipes the keystore itself before
returning None. The gate cannot un-wipe that one, so it detects it and says what
actually happened instead.

⛔ AND TWO CASES WHERE "run it again" IS THE WRONG ADVICE. A 500
auth_delete_failed means the route already revoked the login, so a second run
cannot even mint a token — the owner's web Reset is the recovery, and telling
them to retry would loop them. A 403 not_authorized means the device record has
no syntheticDeviceUid and every branch of the route will refuse it forever.
Both get their own sentence, and `--force` is what actually gets those machines
clean.
"""
import contextlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402

from auth import keystore as ks  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


class _Resp:
    """A requests-shaped response. Every body below is one the real route
    actually returns — 200 {"ok":true,"action":"retired"} is branch 1
    (callerUid === syntheticUid), 404 {"error":"device_not_found"} is its
    not-found answer, 403 {"error":"not_authorized"} is the fall-through for a
    doc with no syntheticDeviceUid, 500 {"error":"auth_delete_failed"} is the
    deliberate keep-the-doc failure."""

    def __init__(self, status_code, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = text if text is not None else (
            json.dumps(body) if body is not None else ""
        )

    def json(self):
        if self._body is None:
            raise ValueError("response carried no JSON body")
        return self._body


@pytest.fixture
def wired(monkeypatch, tmp_path, capsys):
    """The real `run_unpair`, with only its destructive collaborators replaced
    by recorders. The gate, the branch logic, the ordering and every printed
    sentence are the shipped code."""
    state = {
        "device_id": "dev-abc123",
        "paired_uid": "owner-1",
        "token": "tok-live",
        "recoverable": True,
        "resp": _Resp(200, {"ok": True, "action": "retired"}),
        "raises": None,
        "calls": [],
    }

    cfg = tmp_path / "research_config.json"
    cfg.write_text('{"deviceId": "dev-abc123"}', encoding="utf-8")
    legacy = tmp_path / "pipeline_config.json"
    monkeypatch.setattr(research, "RESEARCH_CONFIG_PATH", cfg)
    monkeypatch.setattr(research, "_LEGACY_PIPE_CONFIG_PATH", legacy)

    monkeypatch.setattr(research, "load_device_id", lambda: state["device_id"])
    monkeypatch.setattr(research, "load_paired_uid", lambda: state["paired_uid"])
    monkeypatch.setattr(research, "_fresh_user_mode_id_token", lambda: state["token"])
    monkeypatch.setattr(research, "_sync_spinner_ctx",
                        lambda label: contextlib.nullcontext())

    # Nothing on this machine is a supervisor or a process. "TestPlatform"
    # matches none of the three platform branches, so no schtasks / launchctl /
    # systemctl ever runs.
    monkeypatch.setattr(research, "_supervisor_platform", lambda: "TestPlatform")
    monkeypatch.setattr(research, "_enumerate_research_py_procs", lambda: [])
    monkeypatch.setattr(research, "_kill_pids", lambda pids: 0)

    def _init_fb():
        state["calls"].append("init_firebase")

    def _sweep(db, uid, did, *, stopped_by, summary):
        state["calls"].append(("sweep", uid, did, stopped_by, summary))
        return (1, 0)

    monkeypatch.setattr(research, "init_firebase", _init_fb)
    monkeypatch.setattr(research, "_firebase_db", object())
    monkeypatch.setattr(research, "_sweep_stuck_research_docs_for_device", _sweep)

    def _clear_all(install_id, *, reason):
        state["calls"].append(("clear_all", reason))

    monkeypatch.setattr(ks, "clear_all", _clear_all)
    monkeypatch.setattr(ks, "install_uuid", lambda: "iuid-test")
    monkeypatch.setattr(
        ks, "try_recover",
        lambda install_id: ("current", "rt-1") if state["recoverable"] else None,
    )

    import requests

    def _post(url, **kw):
        state["calls"].append(("post", url))
        if state["raises"] is not None:
            raise state["raises"]
        return state["resp"]

    monkeypatch.setattr(requests, "post", _post)

    state["out"] = lambda: capsys.readouterr().out
    state["cfg"] = cfg
    return state


def _kinds(calls):
    return [c if isinstance(c, str) else c[0] for c in calls]


# ── (a) wipe ONLY when the server confirmed ──────────────────────────────────
#
# ⛔ THE EXIT-CODE ASSERTION COMES LAST IN EVERY TEST BELOW, DELIBERATELY. The
# old `run_unpair` had no return statement at all, so an `rc ==` assertion
# placed first fails against it for free and every behavioural assertion after
# it is never reached — the whole file would then be measuring one thing.
# Behaviour first, status last, so each pin fails on its own account.

def test_an_unminted_token_refuses_and_wipes_NOTHING(wired):
    """⛔⛔ THE SILENT PATH. No request, no status, no exception — and until this
    wave, no log line and no refusal either: execution simply fell through to
    the full wipe."""
    wired["token"] = None
    rc = research.run_unpair()
    out = wired["out"]()

    assert wired["cfg"].exists(), "the local config was deleted on a refusal"
    assert "clear_all" not in _kinds(wired["calls"]), "the keystore was wiped on a refusal"
    assert "post" not in _kinds(wired["calls"]), "a request went out without a token"
    assert "still paired" in out
    assert rc == 2, f"a refusal must exit non-zero, got {rc!r}"


def test_a_non_200_refuses_and_wipes_NOTHING(wired):
    wired["resp"] = _Resp(401, {"error": "unauthorized"})
    rc = research.run_unpair()
    out = wired["out"]()

    assert wired["cfg"].exists()
    assert "clear_all" not in _kinds(wired["calls"])
    # and it names the status rather than shrugging
    assert "401" in out
    assert rc == 2


def test_a_network_failure_refuses_and_wipes_NOTHING(wired):
    """This except also covers the requests/auth.v2_flow import — i.e. offline
    and broken-install alike. It used to log '(continuing)'."""
    wired["raises"] = OSError("Failed to resolve 'super-research.app'")
    rc = research.run_unpair()
    out = wired["out"]()

    assert wired["cfg"].exists()
    assert "clear_all" not in _kinds(wired["calls"])
    assert "could not be reached" in out
    assert rc == 2


def test_a_200_wipes_and_exits_zero(wired):
    rc = research.run_unpair()
    out = wired["out"]()

    assert not wired["cfg"].exists(), "a confirmed retire must wipe local config"
    assert ("clear_all", "unpair") in wired["calls"]
    assert f"Deleted devices/{wired['device_id']}" in out
    assert rc == 0


def test_the_routes_own_device_not_found_CONFIRMS_and_wipes(wired):
    """404 + {"error":"device_not_found"} is the route saying the doc is already
    gone. There is nothing left to strand, so wiping is the correct finish —
    and it must not be reported as a failed retire."""
    wired["resp"] = _Resp(404, {"error": "device_not_found"})
    rc = research.run_unpair()
    out = wired["out"]()

    assert not wired["cfg"].exists()
    assert ("clear_all", "unpair") in wired["calls"]
    assert "already gone" in out
    assert "didn't complete" not in out
    assert rc == 0


def test_an_edge_404_WITHOUT_the_bodys_slug_does_not_confirm(wired):
    """⛔ A wrong FE_BASE_URL, or a rewritten path, answers 404 too. Matching on
    the bare status would read a misconfigured host as 'your device is gone' and
    wipe the machine on it."""
    wired["resp"] = _Resp(404, None, text="<html>404 Not Found</html>")
    rc = research.run_unpair()

    assert wired["cfg"].exists()
    assert "clear_all" not in _kinds(wired["calls"])
    assert rc == 2


def test_a_404_carrying_a_DIFFERENT_slug_does_not_confirm(wired):
    wired["resp"] = _Resp(404, {"error": "not_found"})
    rc = research.run_unpair()

    assert wired["cfg"].exists()
    assert "clear_all" not in _kinds(wired["calls"])
    assert rc == 2


# ── (c) --force restores the old behaviour, deliberately ─────────────────────

def test_force_wipes_even_when_the_server_refused(wired):
    wired["resp"] = _Resp(401, {"error": "unauthorized"})
    rc = research.run_unpair(force=True)
    out = wired["out"]()

    assert rc == 0
    assert not wired["cfg"].exists()
    assert ("clear_all", "unpair") in wired["calls"]
    # and it says plainly what --force left behind
    assert "--force" in out
    assert "still on the server" in out


def test_force_wipes_even_when_no_token_could_be_minted(wired):
    """The 403-forever machine (a device doc with no syntheticDeviceUid) and the
    offline machine both reach --force through this path. Without it, after this
    wave such a machine could never unpair at all."""
    wired["token"] = None
    rc = research.run_unpair(force=True)

    assert rc == 0
    assert not wired["cfg"].exists()
    assert ("clear_all", "unpair") in wired["calls"]


def test_force_still_runs_the_cleanup_a_refusal_skips(wired):
    """The refusal's whole cost is the step-2 orphan kill + supervisor removal.
    --force is what buys it back, so --force must reach step 2."""
    wired["resp"] = _Resp(500, {"error": "auth_delete_failed"})
    rc = research.run_unpair(force=True)
    out = wired["out"]()

    assert "Stopping running processes" in out
    assert "Confirming silence" in out
    assert rc == 0


# ── (e2) the Firestore sweep moved BEHIND the gate ───────────────────────────

def test_a_refusal_does_not_touch_the_owners_or_sharers_runs(wired):
    """⛔⛔ THIS IS WHAT MADE 'nothing changed' A LIE. The sweep stamps
    stoppedBy='unpair_sweep' / summary='Cancelled by Unpair' across the owner's
    AND every sharer's research docs. It used to run BEFORE the POST, so a
    refusal had already cancelled other people's chats."""
    wired["resp"] = _Resp(429, {"error": "rate_limited"})
    rc = research.run_unpair()

    assert "sweep" not in _kinds(wired["calls"])
    assert "init_firebase" not in _kinds(wired["calls"]), (
        "the 10-15s Firestore init ran on a refusal that changed nothing"
    )
    assert rc == 2


def test_the_sweep_runs_AFTER_the_confirmation_and_before_the_wipe(wired):
    """It still has to happen — the route deletes the device doc without
    cascade-updating research docs — and it still runs before step 1's local
    wipe. Only its position relative to the POST changed."""
    rc = research.run_unpair()
    kinds = _kinds(wired["calls"])

    assert kinds.index("post") < kinds.index("sweep"), (
        "the sweep must not precede the confirmation any more"
    )
    assert kinds.index("sweep") < kinds.index("clear_all")
    assert ("sweep", "owner-1", "dev-abc123", "unpair_sweep",
            "Cancelled by Unpair") in wired["calls"]
    assert rc == 0


# ── (e1) the revoke path: the keystore is already gone ───────────────────────

def test_the_revoke_path_does_not_claim_that_nothing_changed(wired):
    """⛔⛔ `_fresh_user_mode_id_token()` IS NOT READ-ONLY ON FAILURE: on a
    genuine RevokedError it calls keystore.clear_all(reason='revoke') before
    returning None. The gate cannot un-wipe that, so it must not print a
    sentence claiming it did nothing."""
    wired["token"] = None
    wired["recoverable"] = False
    rc = research.run_unpair()
    out = wired["out"]()

    assert "Nothing changed" not in out, (
        "the keystore is already gone on this path — the sentence is false"
    )
    assert "sign-in is already gone" in out
    assert "Account" in out and "--force" in out
    assert rc == 2


def test_a_recoverable_keystore_still_gets_the_plain_nothing_changed(wired):
    """The other four causes of a None token (auth/ import failure, empty
    keystore, a transient error on the revoke retry, any other exception) leave
    the keystore alone, and there the plain sentence is true."""
    wired["token"] = None
    wired["recoverable"] = True
    out_rc = research.run_unpair()
    out = wired["out"]()

    assert "Nothing changed" in out
    assert "Run it again, or remove it in Account." in out
    assert out_rc == 2


# ── (f) the cases where "run it again" is wrong advice ───────────────────────

def test_a_500_does_NOT_tell_the_user_to_run_it_again(wired):
    """⛔ The unpair-self route in its own words: 'It is NOT retryable from the
    machine: the revoke above has already run.' Telling them to retry loops
    them through a command that can no longer authenticate."""
    wired["resp"] = _Resp(500, {"error": "auth_delete_failed"})
    rc = research.run_unpair()
    out = wired["out"]()

    assert "Run it again" not in out
    assert "Reset" in out
    assert "auth_delete_failed" in out
    assert "--force" in out
    assert rc == 2


def test_a_403_points_at_force_rather_than_a_retry(wired):
    """⛔ A device doc missing `syntheticDeviceUid` fails all three route
    branches and answers 403 forever. Before this wave such a machine still
    unpaired locally; after it, --force is the only way it ever can."""
    wired["resp"] = _Resp(403, {"error": "not_authorized"})
    rc = research.run_unpair()
    out = wired["out"]()

    assert "Run it again" not in out
    assert "--force" in out
    assert "not_authorized" in out
    assert rc == 2


# ── (h) the refusal says what it skipped ─────────────────────────────────────

@pytest.mark.parametrize("setup", ["no-token", "http", "error"])
def test_every_refusal_names_force_and_the_cleanup_it_skipped(wired, setup):
    """⛔ The code argues IN WRITING that --unpair must ALWAYS run the process
    kill + scheduled-task removal, because orphan daemon/serve processes are the
    root cause of the paired-but-crash-looping state. A refusal skips exactly
    that, so every refusal has to name the two commands that do it."""
    if setup == "no-token":
        wired["token"] = None
    elif setup == "http":
        wired["resp"] = _Resp(502, None, text="bad gateway")
    else:
        wired["raises"] = TimeoutError("read timed out")

    rc = research.run_unpair()
    out = wired["out"]()

    assert "--unpair --force" in out
    assert "--doctor" in out
    assert "On Startup" in out
    # and it certainly did not claim to have stopped anything
    assert "Stopping running processes" not in out
    assert "Confirming silence" not in out
    assert rc == 2


# ── the no-device_id case the gate must NOT capture ──────────────────────────

def test_an_unpaired_machine_still_gets_the_full_cleanup(wired):
    """⛔ When there is no device_id there is nothing to confirm, so the gate
    must not fire: this is the 'prior --unpair left orphan processes and a
    scheduled task behind' case the comment above the gate exists for."""
    wired["device_id"] = ""
    rc = research.run_unpair()
    out = wired["out"]()

    assert "post" not in _kinds(wired["calls"])
    assert "Stopping running processes" in out
    assert "Confirming silence" in out
    assert "nothing to remove server-side" in out
    assert rc == 0


# ── (i) the second caller stays ungated, and the two now DIVERGE ─────────────

def test_pair_rollback_still_wipes_on_a_non_200_while_unpair_refuses(wired):
    """⛔ A SAFETY GATE THAT EXISTS TWICE IS HOW STRETCH 7 WENT WRONG. The same
    POST, the same shape, lives in `_cleanup_partial_pair` — and there wiping
    anyway is CORRECT, because it is pair rollback over half-built local state
    nobody wants. This pins the divergence so neither half gets 'fixed' into
    the other: one 401, two different outcomes."""
    wired["resp"] = _Resp(401, {"error": "unauthorized"})

    rc = research.run_unpair()
    assert "clear_all" not in _kinds(wired["calls"])
    assert wired["cfg"].exists()
    assert rc == 2, "--unpair must refuse a 401"
    wired["out"]()

    wired["calls"].clear()
    research._cleanup_partial_pair("dev-abc123")
    assert ("clear_all", "retire") in wired["calls"], (
        "pair rollback must still wipe on a non-200 — it is not this defect"
    )
    assert not wired["cfg"].exists()


# ── (d) the exit code, and the flag, through the real CLI ────────────────────

def test_main_raises_SystemExit_carrying_the_commands_status():
    """⛔ Returning an int from main() is not enough: `python research.py` calls
    main() bare at the bottom of the file and throws the value away, so only the
    console script would ever see it. `raise SystemExit` works on both entry
    points — which is what --visibility already does two lines up."""
    src = inspect.getsource(research.main)
    assert "raise SystemExit(run_unpair(" in src
    branch = src[src.index("if args.unpair:"):][:600]
    assert "force=bool(args.force)" in branch
    assert "deep=bool(args.deep)" in branch


def test_run_unpair_takes_force_and_returns_a_status():
    sig = inspect.signature(research.run_unpair)
    assert "force" in sig.parameters
    assert sig.parameters["force"].default is False


def _cli(*args, tmp_home):
    """The real CLI in a child process with a throwaway HOME. ⛔ Deliberately
    never `--unpair` itself: that enumerates and kills this developer's real
    daemon-loop/--serve processes. `--visibility unlisted` makes main() reject
    the VALUE with exit 2 after argparse has parsed everything, so an
    undeclared --force shows up as argparse's own 'unrecognized arguments'."""
    env = dict(os.environ, HOME=str(tmp_home), DG_ALERT_AI_COPY="0")
    env.pop("SUPERRESEARCH_STATE_DIR", None)
    return subprocess.run(
        [sys.executable, "research.py", *args],
        cwd=str(REPO), env=env, capture_output=True, text=True, encoding="utf-8", timeout=300,
    )


def test_force_is_a_real_flag_on_the_real_parser(tmp_path):
    r = _cli("--visibility", "unlisted", "--force", tmp_home=tmp_path)
    assert r.returncode == 2, r.stdout[-2000:] + r.stderr[-2000:]
    assert "unrecognized arguments" not in r.stderr, (
        "--force never reached the parser: " + r.stderr[-400:]
    )
    assert "unlisted" in r.stderr


def test_the_force_row_is_on_the_only_discovery_surface():
    """`add_help=False` and nothing calls format_help, so `run_commands_help` is
    the only place a flag can be discovered. --send-logs, --update and
    --uninstall all shipped undocumented for exactly this reason."""
    src = inspect.getsource(research.run_commands_help)
    assert "python research.py --unpair --force" in src
