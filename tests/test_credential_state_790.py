"""7.9-0 — the credential-state classifier, and the advice it is allowed to give.

⛔⛔ THIS FILE EXISTS BECAUSE THE PROGRAM TOLD ITS OWNER TO DESTROY THEIR OWN
COMPUTER. Measured live 2026-09-06: the owner reset their pair code, which
revokes the machine's device token by design; the machine's next run printed
"keystore empty — run `--pair` to establish a refresh token"; and `--pair` does
not repair a machine, it MINTS A NEW ONE. The server generates a fresh random
deviceId at initiate-pair and nothing anywhere reuses the id on disk, so the
machine would have lost its identity — and, because a new device carries no
`visibility` field and absent reads as private, its public listing too. Four
separate sites printed that advice. One of them offered `--unpair && --pair`.

⛔⛔ THE CONFLATION UNDERNEATH IT: "keystore empty" was being read as "not
paired". They are two independent stores. Wiping the keystore leaves deviceId,
pairedUid and pollSecret sitting in research_config.json, untouched. Every site
that got this wrong had the second fact available — two of them had already
read it into a local variable on the line above — and none of them asked.

⭐ SO THE SHARPEST TEST IN THIS FILE IS NOT A CLASSIFICATION TEST. It is
`test_no_remedy_for_a_paired_machine_ever_names_pair`, which walks EVERY state
whose machine still has an id and an owner and refuses the string. A future
sixth state added without thought fails it by construction, which is the only
guard that survives somebody who has not read this docstring.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research  # noqa: E402


# ── the classifier ───────────────────────────────────────────────────────────

def test_no_device_id_is_never_paired():
    """Nothing on disk to lose — this is the one machine that SHOULD pair."""
    assert research.classify_credentials(None, None, False) == \
        research.CRED_NEVER_PAIRED
    assert research.classify_credentials("", "uid-1", True) == \
        research.CRED_NEVER_PAIRED


def test_an_id_without_an_owner_is_orphaned():
    """⭐ A REAL STATE, NOT A ROUNDING ERROR. `clear_paired_uid` drops the owner
    and deliberately keeps the id so a relink can resume — but the relink
    command its own docstring names does not exist in this program, so pairing
    is the only door left and is correct HERE and nowhere else below."""
    assert research.classify_credentials("dev-1", None, True) == \
        research.CRED_ORPHANED
    assert research.classify_credentials("dev-1", "", False) == \
        research.CRED_ORPHANED


def test_a_paired_machine_with_an_empty_keystore_is_no_token():
    """⛔ THE INCIDENT'S OWN STATE. Both facts present on disk, keystore wiped
    by the reset. This is the machine that must never be told to pair."""
    assert research.classify_credentials("dev-1", "uid-1", False) == \
        research.CRED_NO_TOKEN


def test_a_rejected_token_outranks_a_present_one():
    """⛔ THE SERVER'S ANSWER BEATS THE KEYSTORE'S CONTENTS. A token we still
    hold and the server has already refused is not a working credential, and
    ordering these the other way round would report the machine healthy while
    every write 401s."""
    assert research.classify_credentials(
        "dev-1", "uid-1", True, token_rejected=True
    ) == research.CRED_TOKEN_REJECTED
    assert research.classify_credentials(
        "dev-1", "uid-1", False, token_rejected=True
    ) == research.CRED_TOKEN_REJECTED


def test_everything_present_is_healthy():
    assert research.classify_credentials("dev-1", "uid-1", True) == \
        research.CRED_HEALTHY


def test_never_paired_wins_over_a_rejection():
    """⛔ A machine with no id cannot have had a token rejected in any sense
    that matters, and answering "rejected" would send it down a recovery path
    with nothing to recover. The id question is asked first on purpose."""
    assert research.classify_credentials(
        None, "uid-1", True, token_rejected=True
    ) == research.CRED_NEVER_PAIRED


# ── the advice ───────────────────────────────────────────────────────────────

PAIRED_STATES = (research.CRED_NO_TOKEN, research.CRED_TOKEN_REJECTED)


def test_no_remedy_for_a_paired_machine_ever_names_pair():
    """⛔⛔ THE GUARD THIS WHOLE WAVE IS FOR, and it is written over the STATE
    LIST rather than over two literals so that a state added later cannot slip
    past it. `--pair` on a machine that still has an id and an owner discards
    both."""
    for state in PAIRED_STATES:
        lines = research.credential_remedy(state)
        assert lines, f"{state} must say something"
        joined = " ".join(lines)
        advice = " ".join(
            ln for ln in lines if not ln.lstrip().startswith("⛔")
        )
        assert "--pair" not in advice, (
            f"{state} recommends pairing, which would mint a NEW device id "
            f"and drop this machine's public setting: {advice!r}"
        )
        assert "--serve" in joined, f"{state} must name the command that works"


def test_the_recovered_states_warn_against_pairing_by_name():
    """⭐ SILENCE IS NOT ENOUGH HERE. The owner reached for `--pair` because
    four places in this program recommended it and one command printed it as
    the fix; removing the recommendation without saying why leaves the next
    person to rediscover it from the old advice they remember."""
    for state in PAIRED_STATES:
        joined = " ".join(research.credential_remedy(state))
        assert "--pair" in joined, "the warning must name the command"
        assert "NEW computer" in joined


def test_no_remedy_promises_a_timer():
    """⛔ THE OWNER CONCLUDED "it just needed a little time after the reset" and
    was wrong — the serve run wrote the token, and waiting would never have
    done it. A settling-period sentence would send the next owner away for
    nothing, which is the same lie shape as blaming the network."""
    for state in (research.CRED_NEVER_PAIRED, research.CRED_ORPHANED,
                  *PAIRED_STATES):
        joined = " ".join(research.credential_remedy(state)).lower()
        for promise in ("try again in", "shortly", "a few minutes",
                        "wait a", "automatically"):
            assert promise not in joined, (
                f"{state} promises {promise!r}; this state waits for a person"
            )


def test_the_two_pairing_states_do_recommend_pairing():
    """⛔ THE OVER-CORRECTION THIS WAVE MUST NOT MAKE. A machine that never
    paired, and a machine whose owner link is gone, have no other door."""
    for state in (research.CRED_NEVER_PAIRED, research.CRED_ORPHANED):
        joined = " ".join(research.credential_remedy(state))
        assert "--pair" in joined
        assert "--serve" not in joined


def test_inside_a_running_serve_the_remedy_does_not_say_to_start_one():
    """⛔⛔ TWO CONSUMERS ARE ALREADY INSIDE A SERVE — the boot banner and the
    recovery watcher — and telling somebody sitting in front of a running serve
    to start a serve reads as "you did it wrong", when starting it is the one
    thing that makes recovery possible. Cross-verify caught it."""
    for state in PAIRED_STATES:
        joined = " ".join(research.credential_remedy(state, in_serve=True))
        assert "--serve" not in joined
        assert "keep it open" in joined.lower()


def test_outside_a_serve_the_remedy_still_names_the_command():
    """⛔ THE OVER-CORRECTION. A person at a plain prompt has to be told the
    command; only the in-serve caller already has it running."""
    for state in PAIRED_STATES:
        assert "--serve" in " ".join(research.credential_remedy(state))


def test_the_in_serve_variant_still_refuses_to_recommend_pairing():
    """⛔ THE SAFETY PROPERTY IS NOT ALLOWED TO DEPEND ON THE CALLER."""
    for state in PAIRED_STATES:
        lines = research.credential_remedy(state, in_serve=True)
        advice = " ".join(
            l for l in lines if not l.lstrip().startswith("⛔")
        )
        assert "--pair" not in advice


def test_a_healthy_machine_is_told_nothing():
    assert research.credential_remedy(research.CRED_HEALTHY) == []


def test_an_unknown_state_says_nothing_rather_than_guessing():
    """⛔ A remedy invented for a state nobody defined is advice nobody
    reviewed."""
    assert research.credential_remedy("something_new") == []


# ── the consumers ────────────────────────────────────────────────────────────
#
# ⛔⛔ EXTRACTING A HELPER DOES NOT TEST IT. Every assertion above would still
# pass with all eight call sites left exactly as they were, printing exactly the
# advice that nearly cost the owner their machine. These are the tests that
# would actually have caught the incident.

import inspect  # noqa: E402


def _code_only(text: str) -> str:
    """Drop comment lines AND docstrings, keeping every other string literal.

    ⛔⛔ THIS WAVE QUOTES EVERY SENTENCE IT REMOVES, on purpose — a reader who
    finds one of these lines needs to know what it used to say and why it went.
    So a substring search over raw source matches the EXPLANATION rather than
    the defect, and reports a file that is correct as broken. It did exactly
    that on the first run of this test.

    ⛔ STRIPPING COMMENTS IS NOT ENOUGH, which is the part that caught me: the
    retired sentences are quoted in DOCSTRINGS too, and a docstring is not a
    comment. Both go.

    ⭐ AND NO MORE THAN BOTH. Blanking every string literal would delete the
    user-facing sentences this test exists to search, leaving an assertion that
    passes because it can no longer see anything — the shape of a guard that
    cannot fail."""
    import ast as _ast

    doc_lines: set = set()
    try:
        tree = _ast.parse(text)
    except SyntaxError:  # pragma: no cover - the suite would be red anyway
        tree = None
    if tree is not None:
        for node in _ast.walk(tree):
            if not isinstance(
                node,
                (_ast.Module, _ast.FunctionDef, _ast.AsyncFunctionDef,
                 _ast.ClassDef),
            ):
                continue
            body = getattr(node, "body", None)
            if not body:
                continue
            first = body[0]
            if (isinstance(first, _ast.Expr)
                    and isinstance(first.value, _ast.Constant)
                    and isinstance(first.value.value, str)):
                doc_lines.update(
                    range(first.lineno, (first.end_lineno or first.lineno) + 1)
                )
    return "\n".join(
        l for i, l in enumerate(text.splitlines(), 1)
        if i not in doc_lines and not l.strip().startswith("#")
    )


RESEARCH_CODE = _code_only(
    __import__("pathlib").Path(research.__file__).read_text(encoding="utf-8")
)


RETIRED_SENTENCES = [
    # The founding one: printed to the owner on 2026-09-06.
    "keystore empty — run",
    # The worst of them: deletes the device server-side AND the local config,
    # then mints a different machine.
    "--unpair && ",
    # Printed on the one code path that had already proven the device is paired.
    "or run --pair on this PC",
    # False wherever the program was started by hand, which is supported.
    "respawn the backend automatically",
    # False whenever a device id is on disk, which is exactly when it printed.
    "Device not paired yet",
]


def test_every_retired_sentence_is_gone():
    for sentence in RETIRED_SENTENCES:
        assert sentence not in RESEARCH_CODE, (
            f"{sentence!r} is back in research.py — see "
            f"tests/test_credential_state_790.py for why it was removed"
        )


def test_the_advice_sites_all_delegate():
    """⛔ A COUNT, BECAUSE THE ALTERNATIVE IS NAMING EIGHT FUNCTIONS AND
    WATCHING THE NINTH SITE SKIP THE LIST. Eight sites were wrong; each now
    asks the classifier. If somebody deletes a call and hand-writes the advice
    back, this drops."""
    # ⛔ THE DEFINITION IS NOT A CALL SITE. The first version counted every
    # occurrence of the name, including `def credential_remedy(`, so eight was
    # satisfied by SEVEN consumers plus the definition — one site could regress
    # to hand-written advice and this would still pass. Cross-verify caught it.
    calls = RESEARCH_CODE.count("credential_remedy(") - RESEARCH_CODE.count(
        "def credential_remedy("
    )
    assert calls >= 8, f"only {calls} call sites delegate"


def test_the_recovery_advice_is_reachable_from_a_rest_only_command():
    """⛔⛔ THE WHOLE POINT OF THE PURE CLASSIFIER. `--visibility` and its
    siblings deliberately never build a Firestore client — that is why they use
    the REST path — so an advice function that needed one could not be called
    from the commands that most need to explain themselves. `credential_state_now`
    must reach its answer from disk and the keystore alone."""
    src = inspect.getsource(research.credential_state_now)
    assert "init_firebase" not in src
    assert "_firebase_db" not in src
    assert "load_device_id()" in src and "load_paired_uid()" in src


def test_a_keystore_that_cannot_be_read_does_not_recommend_pairing(monkeypatch):
    """⛔ FAILING CLOSED IN THE SAFE DIRECTION. If the keystore probe itself
    throws, the machine still has its id and owner on disk — so the answer is
    the recoverable state, never the one that tells them to start over."""
    monkeypatch.setattr(research, "load_device_id", lambda: "dev-1")
    monkeypatch.setattr(research, "load_paired_uid", lambda: "uid-1")
    import auth.keystore as ks

    def _boom(*a, **kw):
        raise RuntimeError("keychain locked")

    monkeypatch.setattr(ks, "try_recover", _boom)
    state = research.credential_state_now()
    assert state == research.CRED_NO_TOKEN
    advice = " ".join(
        ln for ln in research.credential_remedy(state)
        if not ln.lstrip().startswith("⛔")
    )
    assert "--pair" not in advice
