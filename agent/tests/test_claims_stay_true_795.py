"""The claims this package makes about itself have to stay true.

⛔⛔ WHY THIS FILE EXISTS: FOUR MUTANTS SURVIVED 7.9-5's FIRST HARNESS RUN, AND
ALL FOUR PUT A FALSE CLAIM BACK. `__init__.py` could go back to promising the
package "can never control devices"; SKILL.md could go back to calling a pair
code "NOT a password"; TESTMATRIX.md could go back to "no bridge unit test yet"
for a route tested since 7.9-1 — and nothing anywhere went red. I corrected four
false claims and pinned none of them, which is the same mistake 7.9-3 recorded
(seventeen repair mutants survived because the repairs were unpinned).

⭐ THE TWO THAT DID DIE were SKILL.md's `device-remove` sentences, and only
because `test_unlink_copy_795.py` sweeps a phrase list across the shipped files.
A sweep for the OLD wording catches a revert to that exact wording; it cannot
catch a NEW false claim, and it cannot notice a true claim being deleted. Both
directions are pinned here: the fact is present AND the falsehood is absent.

⛔ ASSERTIONS RUN OVER CODE ONLY for the Python files, because the comment
explaining each correction quotes the claim it replaced — the trap that has bitten
this repo four times in one wave before.
"""

from pathlib import Path


AGENT = Path(__file__).resolve().parents[1]


def _text(rel: str) -> str:
    src = (AGENT / rel).read_text(encoding="utf-8")
    if rel.endswith(".py"):
        from conftest import code_only
        return code_only(src)
    return src


def _flat(rel: str) -> str:
    return " ".join(_text(rel).split())


# ── the package contract (`facade/__init__.py`) ───────────────────────────────

def test_the_contract_does_not_claim_it_cannot_control_devices():
    """⛔⛔ THE SURVIVOR THIS KILLS (C1). It was false on all four verbs from the
    day `/device/pair`, `/device/remove` and `/device/decide` shipped in 7.9-1 —
    in the file whose entire job is to say what this package will not do."""
    flat = _flat("facade/__init__.py")
    assert "can never control devices" not in flat
    assert "Research-only" not in flat


def test_the_contract_says_what_is_actually_true_about_device_control():
    """The replacement claim has to survive too — a deletion that left the bullet
    out entirely would pass the test above.

    ⛔⛔ AND THE FIRST REPLACEMENT WAS ITSELF FALSE. It said every device verb
    forwards to a web route; `device-visibility` PATCHes the device document
    directly, and the bridge handler's own docstring says so. So the claim is now
    the narrower true one — never writes MEMBERSHIP — and the exception is named
    out loud, which is the part this pins."""
    flat = _flat("facade/__init__.py")
    assert "never writes MEMBERSHIP" in flat
    assert "holds no admin credential" in flat
    assert "device-visibility` is the one device verb that does NOT" in flat
    # the false version must not come back
    assert "Every device verb here forwards" not in flat


def test_the_contract_stops_enumerating_writers_by_hand():
    """⛔⛔ THE ENUMERATION WAS WRONG TWICE — "research docs + device-queue start
    docs", then a four-item list that was still seven writers short. A prose list
    of writers cannot be kept true by hand, so the contract points at the derived
    allowlist instead of carrying a copy."""
    flat = _flat("facade/__init__.py")
    assert "test_app_plane_unchanged.py" in flat
    assert "derived from the code" in flat
    assert "(research docs +" not in flat
    # and the second wrong list must not come back either
    assert "and one access-request document" not in flat


def test_the_contract_still_holds_the_boundaries_that_did_not_change():
    """The three original hard boundaries are the reason the file exists; a
    rewrite of the two false bullets must not have cost them."""
    flat = _flat("facade/__init__.py")
    assert "NEVER imports or mutates research-automate" in flat
    assert 'OWN secret store namespace ("super-agent")' in flat
    assert "existing Firestore rules" in flat


# ── the skill's pair-code claim (`facade/skill/SKILL.md`) ─────────────────────

def test_the_skill_does_not_call_a_pair_code_harmless():
    """⛔⛔ THE SURVIVOR THIS KILLS (C3). "An access code is NOT a secret … NOT a
    password, credential" was false: `/api/devices/claim` grants OWNERSHIP to
    whoever presents a code against a device with no owner, and unlink produces
    exactly that state. 7.7A's three changes — the code moved to an admin-only
    entry, rotation on every membership loss, an owner-only non-enumerating
    reveal — only make sense if it IS a credential."""
    flat = _flat("facade/skill/SKILL.md")
    for false in ("is NOT a secret", "NOT a password", "public pairing code"):
        assert false not in flat, f"SKILL.md says “{false}” again"


def test_the_skill_says_what_holding_a_pair_code_means():
    """⛔⛔ `"claim" in flat` WAS SATISFIED 290 LINES AWAY — by "makes a claim about
    a conversation that did not happen". Measured: deleting the whole replacement
    clause left all three assertions green, so the one fact this file exists to
    keep true was unpinned. The clause is pinned as a PHRASE now, not by three
    words that each occur somewhere in a 511-line file."""
    flat = _flat("facade/skill/SKILL.md")
    assert "It DOES let whoever holds it claim" in flat
    assert "never repeat it back" in flat
    assert "not a leak" in flat, (
        "the behavioural half must survive too — the model was refusing codes, "
        "and that is why the bullet exists at all")


def test_the_skill_still_tells_the_model_never_to_refuse_a_code():
    """⛔ THE HALF THAT WAS ALWAYS RIGHT. The bullet's false justification was
    replaced; its instruction must not have gone with it."""
    flat = _flat("facade/skill/SKILL.md")
    assert "NEVER refuse it" in flat
    # ⛔ `"device-add" in flat` did nothing — it occurs eight times across the
    # file and none of them is in the bullet under test.
    assert "means run **`sr.py device-add <code>`** right away" in flat


# ── the test matrix (`agent/TESTMATRIX.md`) ──────────────────────────────────

def test_the_matrix_claims_no_route_is_untested_when_it_is_tested():
    """⛔ THE SURVIVOR THIS KILLS (C6). Three rows said "live-only; no bridge unit
    test yet" for routes tested since 7.9-1 — so the newest and least-proven work
    was the work the file described as unproven, and the reverse."""
    flat = _flat("TESTMATRIX.md")
    assert "no bridge unit test yet" not in flat


def test_the_matrix_admits_it_was_wrong_rather_than_quietly_fixing_it():
    """⛔⛔ THE FILE WAS WRONG TWICE IN ONE WAVE — first the inherited version, then
    my rebuild of it. What keeps a document honest is not a corrected sentence but
    a recorded reason it was wrong, so the next person knows which claims to
    distrust. This pins that the admission survives a tidy-up."""
    flat = _flat("TESTMATRIX.md")
    assert "KEPT BEING WRONG" in flat
    assert "IT NOW CLAIMS LESS" in flat
    # the specific falsehoods it confessed to must not come back
    assert "no bridge unit test yet" not in flat
    assert "the generator carries an assertion" not in flat
    assert "862 tests" not in flat


def test_the_matrix_no_longer_claims_a_coverage_credit_it_cannot_derive():
    """⛔⛔ THE `GET /healthz` CREDIT WAS AN ARTEFACT. The only test touching it
    sends `Host: evil.com` and asserts a 403 raised BEFORE the handler runs, so
    the credit came from instrumenting the request entry point rather than the
    handler. Per-route coverage is measured out-of-band; the file says so instead
    of implying the table is self-verifying.

    ⭐ ROUTE COMPLETENESS is the half that IS derivable, and
    `test_route_matrix_795.py` asserts it — which is the guard the old text
    falsely claimed to have."""
    flat = _flat("TESTMATRIX.md")
    assert "HANDLER METHODS, not its request entry" in flat
    assert "test_route_matrix_795.py" in flat


def test_the_matrix_still_names_its_thin_spots():
    """The honest half, kept: three routes are driven by nothing that asserts
    their own behaviour, and the row that used to stand for one of them said it
    was covered."""
    flat = _flat("TESTMATRIX.md")
    assert "ARE THE THIN SPOTS" in flat
    for route in ("`GET /login`", "`GET /healthz`", "`GET /icons/<name>`"):
        assert route in flat
