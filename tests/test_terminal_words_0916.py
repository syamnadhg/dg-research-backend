"""Wave 9 — the terminal's words must name controls that exist, and the wire
identifiers behind them must NOT move.

⛔⛔ THREE SEPARATE FALSEHOODS, ALL OF THEM PRINTED, none of them measured.
  1. `--unpair` listed "• firebase-service-account.json  (needed to re-pair)"
     among the things it had PRESERVED. There is no such file: `init_firebase`
     says so in its own docstring ("No Admin SDK; no firebase-service-account
     .json on disk"), the Track D pair flow is keystore-only, and `run_unpair`'s
     own docstring lists exactly two preserved things. The sentence invented a
     credential and then told the reader it was load-bearing.
  2. Five sentences sent people to "Account → Manage devices". That page does
     not exist, and the web app's own copy file names that exact string as
     non-existent (src/lib/devices/reset-recovery-copy.ts MANAGE_DEVICES_PATH).
     Manage devices is under SETTINGS; the Account page holds the device tiles
     and their Unlink buttons. research.py said "Settings → Manage devices"
     correctly in one place and the wrong thing in five, so the file disagreed
     with itself.
  3. The revoked-session remedy offered two doors — the Approve link and the
     code on the tile — and BOTH close at the same 15-minute mark: the claim
     route throws code_expired past `pairCodeExpiresAt` and the reveal route
     answers 410 reset_expired. The relink give-up sentence was worse than
     mis-worded, it was dead BY CONSTRUCTION: it fires only after
     MAX_RECOVERY_WALLCLOCK_SEC (an hour) and offered a code whose window is
     fifteen minutes, so the code it named had always expired.

⭐ THE WORD ITSELF IS THE WEB APP'S. It calls this value an "Access code" in
every label, error and placeholder; research.py had ZERO occurrences of the
phrase and the agent was half migrated, saying each in neighbouring lines of the
same file.

⛔⛔ AND THE RENAME HAD A FLOOR UNDER IT THAT IS EASY TO BREAK: the wire
identifiers are not prose. `pairCode`, `pairCodeWarning`, `PAIR_CODE_SHOWN`, the
routes /api/devices/pair-code and reset-pair-code and the local `pair_code` are
all read by something else, and renaming one is a defect rather than a cleanup.
So the tests here that pin the new wording pin the OLD identifier in the same
breath — a single test that fails if the label did not move AND fails if the
wire did.
"""
import ast
import contextlib
import inspect
import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402

from auth import keystore as ks  # noqa: E402


def code_only(text: str) -> str:
    """Comments and docstrings out; every other string literal kept.

    ⛔⛔ EVERY GUARD IN THIS FILE THAT SEARCHES SOURCE NEEDS THIS, and the first
    version of two of them did not have it and FAILED — on their own
    explanations. This wave quotes each sentence it removed, verbatim, in the
    comment that says why it went; so a raw substring search finds the
    explanation and reports corrected code as broken. Three separate waves have
    recorded being bitten by this, and it bit again here.

    ⭐ AND NO MORE THAN COMMENTS AND DOCSTRINGS. Blanking every string literal
    would delete the printed sentences these tests exist to read, leaving
    assertions that pass because they can no longer see anything."""
    text = textwrap.dedent(text)
    doc_lines: set = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:  # pragma: no cover - the suite would be red anyway
        tree = None
    if tree is not None:
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
                    range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return "\n".join(
        ln for i, ln in enumerate(text.splitlines(), 1)
        if i not in doc_lines and not ln.strip().startswith("#"))


def test_the_blanking_helper_actually_blanks():
    """⛔ A STRIPPER THAT SILENTLY RETURNS ITS INPUT TURNS EVERY GUARD BELOW
    GREEN. The TypeScript twin of this helper did exactly that for 222 comment
    lines while claiming they were blanked, and a mutant proved nothing was
    measured. So it is driven on a sample with all three shapes."""
    sample = 'def f():\n    """doc says REMOVED_SENTENCE."""\n    # comment says REMOVED_SENTENCE\n    return "printed says KEPT_SENTENCE"\n'
    out = code_only(sample)
    assert "REMOVED_SENTENCE" not in out
    assert "KEPT_SENTENCE" in out


# ── driving `--unpair` for real ──────────────────────────────────────────────
#
# ⛔ THE SAME SHAPE AS tests/test_unpair_gate_0916.py's `wired`, and deliberately
# its own copy rather than a shared conftest fixture: that file pins the GATE and
# this one pins the SENTENCES, and a fixture edited for one would silently move
# the other. Everything destructive is replaced; every printed line is shipped
# code.

class _Resp:
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
def unpair(monkeypatch, tmp_path, capsys):
    state = {
        "device_id": "dev-abc123",
        "paired_uid": "owner-1",
        "token": "tok-live",
        "recoverable": True,
        "resp": _Resp(200, {"ok": True, "action": "retired"}),
    }

    cfg = tmp_path / "research_config.json"
    cfg.write_text('{"deviceId": "dev-abc123"}', encoding="utf-8")
    monkeypatch.setattr(research, "RESEARCH_CONFIG_PATH", cfg)
    monkeypatch.setattr(research, "_LEGACY_PIPE_CONFIG_PATH",
                        tmp_path / "pipeline_config.json")
    monkeypatch.setattr(research, "load_device_id", lambda: state["device_id"])
    monkeypatch.setattr(research, "load_paired_uid", lambda: state["paired_uid"])
    monkeypatch.setattr(research, "_fresh_user_mode_id_token",
                        lambda: state["token"])
    monkeypatch.setattr(research, "_sync_spinner_ctx",
                        lambda label: contextlib.nullcontext())
    monkeypatch.setattr(research, "_supervisor_platform", lambda: "TestPlatform")
    monkeypatch.setattr(research, "_enumerate_research_py_procs", lambda: [])
    monkeypatch.setattr(research, "_kill_pids", lambda pids: 0)
    monkeypatch.setattr(research, "init_firebase", lambda: None)
    monkeypatch.setattr(research, "_firebase_db", object())
    monkeypatch.setattr(
        research, "_sweep_stuck_research_docs_for_device",
        lambda db, uid, did, *, stopped_by, summary: (1, 0))
    monkeypatch.setattr(ks, "clear_all", lambda install_id, *, reason: None)
    monkeypatch.setattr(ks, "install_uuid", lambda: "iuid-test")
    monkeypatch.setattr(
        ks, "try_recover",
        lambda install_id: ("current", "rt-1") if state["recoverable"] else None)

    import requests
    monkeypatch.setattr(requests, "post", lambda url, **kw: state["resp"])

    state["out"] = lambda: capsys.readouterr().out
    return state


def test_the_unpair_receipt_does_not_invent_a_credential_file(unpair):
    """⛔⛔ THE SURVIVING FALSE SENTENCE, DRIVEN. It printed on the DEFAULT
    `--unpair` — the path most people take — and named a file that has never
    existed on this machine as something they would need in order to re-pair.

    ⭐ THE POSITIVE HALF IS WHAT STOPS THIS BEING A VACUOUS NEGATIVE: deleting
    the whole preserved-on-disk block would satisfy an "is not there" assertion
    on its own, so the two lines that ARE true have to still be there."""
    assert research.run_unpair() == 0
    out = unpair["out"]()

    assert "Preserved on disk" in out, "the receipt itself must still render"
    assert "queues/" in out, "the preserved list must still name what is real"
    assert "browser-profile" in out
    assert "firebase-service-account" not in out, (
        "there is no such file on disk — init_firebase's own docstring says so, "
        "and run_unpair's docstring lists only the profiles and queues/"
    )
    assert "needed to re-pair" not in out


def test_neither_unpair_receipt_branch_names_the_file():
    """⛔ THE OTHER BRANCH IS UNREACHABLE FROM THE DEFAULT RUN, and removing the
    bullet from one copy while leaving the other is exactly how this sentence
    would survive: the `--deep` receipt has its own print block. Read over the
    function's whole source so both are covered at once."""
    src = code_only(inspect.getsource(research.run_unpair))
    assert src.count("Preserved on disk") == 2, (
        "both receipt branches must still exist, or this guard reads nothing"
    )
    assert "firebase-service-account" not in src
    assert "needed to re-pair" not in src


def test_no_unpair_refusal_sends_anybody_to_a_page_that_does_not_exist(unpair):
    """⛔⛔ THE REFUSALS ARE THE SENTENCES SOMEBODY READS WHEN THEY ARE ALREADY
    STUCK, and three of the four sent them to a page the web app does not have.
    Each branch is driven, because the wording lives in an if/elif chain and a
    source read cannot tell which arm a given machine reaches."""
    # (i) the keystore is already gone: the only door left is the web app
    unpair["token"] = None
    unpair["recoverable"] = False
    assert research.run_unpair() == 2
    out = unpair["out"]()
    assert "Account → Manage devices" not in out
    assert "Account page" in out, "it must still name where Unlink lives"
    assert "--unpair --force" in out

    # (ii) a 500: the route already revoked the login, so Reset is the recovery
    unpair["token"] = "tok-live"
    unpair["recoverable"] = True
    unpair["resp"] = _Resp(500, {"error": "auth_delete_failed"})
    assert research.run_unpair() == 2
    out = unpair["out"]()
    assert "Account → Manage devices" not in out
    assert "Settings → Manage devices" in out, (
        "Reset lives under Settings, and this is the branch that names Reset"
    )
    assert "Reset" in out

    # (iii) a 403: the record predates the pairing format and will refuse forever
    unpair["resp"] = _Resp(403, {"error": "not_authorized"})
    assert research.run_unpair() == 2
    out = unpair["out"]()
    assert "Account → Manage devices" not in out
    assert "Account page" in out
    assert "--unpair --force" in out


def test_the_whole_machine_stops_naming_the_page_that_does_not_exist():
    """⛔⛔ FIVE SITES SAID IT AND ONE SAID IT RIGHT, so a per-site guard would
    have let the sixth through. This is written over the FILE, the way
    tests/test_credential_state_790.py's retired-sentence guard is, because the
    lesson of that incident is that the wrong sentence grows back somewhere
    nobody thought to look.

    ⛔ COMMENTS AND DOCSTRINGS OUT: this wave quotes the string it removed, in
    order to explain why, so a raw search matches the explanation."""
    code = code_only(Path(research.__file__).read_text(encoding="utf-8"))

    assert "Account → Manage devices" not in code
    # ⭐ AND THE RIGHT NAME IS STILL USED, or this passes on a file that simply
    # stopped telling anybody where to go.
    assert code.count("Settings → Manage devices") >= 3


# ── the revoked-session remedy ───────────────────────────────────────────────

PAIRED = (research.CRED_NO_TOKEN, research.CRED_TOKEN_REJECTED)


@pytest.mark.parametrize("state", PAIRED)
def test_the_remedy_carries_the_window_and_the_way_past_it(state):
    """⛔⛔ BOTH DOORS THE OLD ADVICE NAMED CLOSE AT THE SAME MOMENT. "click
    Approve in the reset email, or use the code on this computer's tile" was
    true for fifteen minutes and this branch prints to people who are long past
    them — the claim route answers code_expired and the reveal route answers 410
    reset_expired. The instruction that still works is "press Reset again", for
    as long as the computer is listed, because the reset route has no pairState
    guard.

    ⭐ AND IT IS THE WEB'S AND THE AGENT'S OWN COPY, not a fourth variant:
    src/lib/devices/reset-recovery-copy.ts RESET_AGAIN_STEP / ENTER_CODE_PATH /
    MANAGE_DEVICES_PATH, and agent/facade/cli.py's _PAIR_FAILURES."""
    lines = research.credential_remedy(state)
    joined = " ".join(lines)

    assert "15 minutes" in joined, "the window is the fact that makes the rest true"
    assert "NEWEST reset email" in joined, (
        "a second Reset rotates the code, so an older email answers code_not_found"
    )
    assert "press Reset again" in joined
    assert "Settings → Manage devices" in joined
    assert "Account → Pipeline Connection → + add device" in joined, (
        "while a computer is listed that section shows no code field, only the "
        "+ add device button — so the section alone is not enough"
    )
    # ⛔ THE RETIRED SENTENCE, BY NAME. It offered a door with no window on it.
    assert "on this computer's tile under Account" not in joined


@pytest.mark.parametrize("state", PAIRED)
def test_the_remedy_still_refuses_to_offer_pairing_as_the_action(state):
    """⛔ THE OVER-CORRECTION GUARD FOR THIS EDIT. The new advice adds two
    sentences to the branch whose whole reason for existing is that `--pair`
    mints a NEW device id. `--pair` may appear only in the ⛔ warning line."""
    lines = research.credential_remedy(state)
    advice = " ".join(
        ln for ln in lines if not ln.lstrip().startswith("⛔"))
    assert "--pair" not in advice
    assert "--serve" in " ".join(lines)


def test_the_reset_email_comment_no_longer_claims_it_carries_no_code():
    """⛔⛔ A STALE COMMENT IS WHAT RE-GROWS THE WRONG SENTENCE UNDER IT. This
    one asserted the reset mail "contains NO CODE — the body renders an Approve
    button and nothing else", and that stopped being true in wave 2:
    src/lib/email/sendResetCode.ts renders a labelled block headed "Your new
    access code" with the code printed as XXXX-XXXX beside the Approve link.

    ⛔ THIS IS THE ONE TEST IN THE FILE THAT READS COMMENTS ON PURPOSE, because
    here the defect WAS a comment. Everything else goes through `code_only`.

    ⛔⛔ AND IT NORMALISES WHITESPACE FIRST. The first version searched the raw
    source, and it passed for the wrong reason: the corrected comment quotes the
    old claim, and the quote happened to fall across a line break, so the phrase
    was not contiguous. Re-wrapping that comment by one word would have flipped
    the test — a pin held up by an accident of formatting. The fix was on both
    sides: the comment no longer restates the false sentence verbatim, and this
    reads a whitespace-flattened copy so no wrap can hide anything."""
    flat = " ".join(
        inspect.getsource(research.credential_remedy).replace("#", " ").split())

    assert "renders an Approve button and nothing else" not in flat, (
        "the email has carried the code since wave 2 — see sendResetCode.ts, "
        "which prints it as XXXX-XXXX under its own heading"
    )
    # ⛔ NO GUARD ON THE PHRASE "carries no code" ITSELF, and that is deliberate
    # rather than an omission: this repo's convention is that a corrected comment
    # QUOTES the claim it is retiring, so the corrected version necessarily names
    # it in order to deny it. A negative on those words would forbid the record
    # and could only be satisfied by deleting the history. The pin is the
    # sentence above plus the two positive facts below, which no version of the
    # stale comment could have supplied.
    # ⭐ THE POSITIVE HALF, which the stale comment could not have satisfied.
    assert "Your new access code" in flat, (
        "the corrected comment must name what the email actually renders"
    )
    assert "410 reset_expired" in flat, (
        "and why the tile's code is not a second door: the reveal route closes "
        "with the same 15-minute window"
    )


def test_the_relink_giveup_no_longer_offers_an_expired_code():
    """⛔⛔ DEAD BY CONSTRUCTION, WHICH IS WHY NO WORDING GUARD CAUGHT IT. The
    branch fires at MAX_RECOVERY_WALLCLOCK_SEC and the code's window is
    RESET_WINDOW_MINUTES, so the arithmetic alone condemns the sentence: 3600
    seconds against fifteen minutes. The test reads both numbers off the code
    rather than restating them, so a future change to either is caught here."""
    src = code_only(inspect.getsource(research._revoked_recovery_loop))  # noqa: SLF001
    branch = src[src.index("MAX_RECOVERY_WALLCLOCK_SEC:"):]
    branch = branch[:branch.index("poll_secret = load_poll_secret()")]

    assert "MAX_RECOVERY_WALLCLOCK_SEC = 3600" in src, (
        "the give-up delay is what makes an emailed code always expired here"
    )
    assert "use the code you were emailed" not in branch
    assert "press Reset again" in branch
    assert "Settings → Manage devices" in branch
    # ⛔ AND PAIRING STAYS BEHIND ITS CONDITION, which is still correct.
    assert "only if it is GONE" in branch


# ── the words on screen, and the identifiers under them ──────────────────────

def test_the_pairing_screen_uses_the_webs_word_and_keeps_every_wire_name():
    """⛔⛔ ONE TEST FOR BOTH HALVES ON PURPOSE. The screen had to move to the
    web app's word and the identifiers had to NOT move, and those are the two
    ways this edit could have been wrong — a label left saying "Pair code" while
    the web says "Access code", or a helpful sweep that renamed the telemetry
    event and the JSON field along with it. Split into two tests, the identifier
    half would have passed before this wave and measured nothing."""
    src = code_only(inspect.getsource(research.cmd_pair_v2))

    # the words
    assert "'Access code'" in src, "the headline label above the eight characters"
    assert "Requesting an access code" in src, "the spinner while it is minted"
    assert "Pair code" not in src, "the old label must be gone, not duplicated"

    # the identifiers, which are read by something else
    assert "tm.Ev.PAIR_CODE_SHOWN" in src, "telemetry event name — not prose"
    assert 'captured["pair_code"]' in src, "the local the flow reads back"
    assert "def _on_code(device_id: str, pair_code: str)" in src


def test_the_pair_session_and_the_visibility_command_agree_on_the_word():
    """⛔ THE TWO SENTENCES ARE FOUR PRINTED LINES APART ON ONE SCREEN in the
    pair session, and the third is what `--visibility` says later about the same
    setting. A half-migration leaves a machine calling one value two names."""
    stage = code_only(
        inspect.getsource(research._continue_pair_stages_2_to_6))  # noqa: SLF001
    vis = code_only(inspect.getsource(research.run_visibility))

    assert "Anyone you give the access code to" in stage
    assert "Only people you give the access code to can ask." in stage
    assert "only people you give the access code to can ask." in vis
    assert "pair code" not in stage
    assert "pair code" not in vis


def test_the_route_paths_and_the_json_field_are_untouched():
    """⛔⛔ THE FLOOR UNDER THE RENAME. These are not words on a screen: the two
    FE routes are URLs the machine POSTs to, and `pairCode` is the field name the
    claim response carries. A sweep that renamed them would break pairing
    silently — the machine would ask for a path the app does not serve.

    ⭐ CONJOINED WITH THE RENAME so the test as a whole could not have passed
    before this wave: the first assertion is the new wording."""
    text = Path(research.__file__).read_text(encoding="utf-8")
    assert "Requesting an access code" in text, "the rename happened"
    assert "/api/devices/pair-code" in text
    assert "reset-pair-code" in text
    assert "PAIR_CODE_SHOWN" in text


def test_the_storage_403_hints_name_a_repair_that_is_allowed():
    """⛔⛔ THE SAME DEFECT `credential_remedy` EXISTS TO FORBID, SITTING OUTSIDE
    ITS REACH. Two of these three hints said "try Reset Pair Code → re-pair" and
    "(re-pair to refresh)" — pairing, recommended to a machine that still holds a
    device id, which discards that id along with its sharers and its public
    setting. The guard in tests/test_credential_state_790.py reads
    `credential_remedy`'s return value only, so it never saw them; they are in
    that file's RETIRED_SENTENCES now, and this pins the replacement.

    ⛔ THE THIRD NAMED A CONTROL THAT HAS NEVER EXISTED: "Manage devices → Add
    sharer". There are zero hits for add sharer / addSharer in the web app and
    its Manage-Sharers popup takes only onRevoke."""
    src = code_only(
        inspect.getsource(research._download_user_source_via_storage_rest))  # noqa: SLF001
    i = src.index("403 root: path is for THIS device's owner")
    hints = src[i:src.index("403 diagnostic raised")]

    assert "re-pair" not in hints, (
        "this machine still has a device id; --pair would mint a new one"
    )
    assert "Add sharer" not in hints
    assert "--restart" in hints, "a restart is what refreshes a synth-token claim"
    assert "Settings → Manage devices" in hints
    assert "Account → Pipeline Connection → + add device" in hints, (
        "the real way a sharer gets in is the owner giving them the code"
    )
    assert "Review on the Account banner" in hints, (
        "and the other real way is approving their access request"
    )
    # ⛔ `sharedWith` IS THE FIRESTORE FIELD NAME and firestore.rules reads it.
    assert "sharedWith" in hints


def test_the_fourth_403_hint_was_not_missed():
    """⛔⛔ THERE WERE FOUR, NOT THREE. The measurement found the trio in
    `_download_user_source_via_storage_rest`; the AUDIO upload carries a fourth
    with both of the same faults — "re-pair via FE Account → Add Device" named a
    page the app does not have AND recommended the command that discards this
    machine's identity. A per-function guard would have shipped it.

    ⭐ READS THE COMPILED CONSTANT, NOT THE SOURCE, and that is the point here:
    the corrected hint is a hand-wrapped implicit concatenation with a comment
    sitting in the middle of it, so a source search can be satisfied by a
    fragment and cannot see the sentence a person actually reads. `co_consts`
    holds exactly the one string `log()` is handed. It also proves the comment
    did not break the concatenation into two literals."""
    consts = [c for c in research._upload_audio_via_storage_rest.__code__.co_consts  # noqa: SLF001
              if isinstance(c, str) and "403 hint (after retries)" in c]
    assert len(consts) == 1, (
        f"expected one assembled hint, found {len(consts)} — a comment or an "
        f"editing slip has split the implicit concatenation"
    )
    hint = " ".join(consts[0].split())

    assert "Account → Add Device" not in hint, "that page does not exist"
    assert "re-pair" not in hint, (
        "this machine still has a device id; --pair would mint a new one and "
        "drop its sharers and its public setting"
    )
    assert "press Reset in Settings → Manage devices" in hint
    assert "approve the newest email while this computer is running" in hint
    # ⛔ THE REST OF THE HINT MUST SURVIVE, or the negatives above pass on a
    # sentence that was simply gutted.
    assert "token.ownerUid == path-uid" in hint
    assert "Manage Sharers" in hint, (
        "the read-only sharer check IS a real control on the Account page"
    )
    assert "firebase deploy --only storage" in hint
