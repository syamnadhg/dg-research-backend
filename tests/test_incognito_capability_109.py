"""The research computer can say whether it understands a run that keeps nothing.

⛔⛔ THE HALF THAT STOPS AN OLD WHEEL SILENTLY SAVING. Wave 10.9's incognito run
is a promise about a pipeline, and the pipeline runs on a wheel that ships when
somebody upgrades their computer — which nothing forces and nothing counts. A
machine built before this wave reads the record, sees a research id it has no
opinion about, and runs the ordinary pipeline: it uploads the podcast, writes
the `audios` row, stamps its events thirty days out and parks the run for
Resume. The rules refuse each of those writes on every wheel, so nothing is
KEPT either way — but the run dies halfway through on a 403 and the person has
already paid for it.

`incognitoRuns` on the device document is what lets the app decline up front.

⭐ THE PINS EXECUTE THE PREDICATE AND THE PUBLISHER, and every refusal here is
paired with its accept polarity: a predicate that answered `False` for
everything would pass every "an ordinary research is not incognito" assertion
and take the whole feature away silently.
"""
import os
import re
from pathlib import Path

import pytest

import research


# ══ 1. the id is the signal, and it has exactly one shape ═════════════════

@pytest.mark.parametrize("rid", [
    "incog_1758400000000_1",
    "incog_1700000000000_999999",
])
def test_an_id_this_app_mints_is_incognito(rid):
    """⭐ ACCEPT POLARITY FIRST. Without these the refusals below are satisfied
    by a predicate that says no to everything."""
    assert research._is_incognito_research(rid) is True


@pytest.mark.parametrize("rid", [
    "chat_1758400000000_1",        # the web's ordinary fresh-chat mint
    "agent-4f2c1a9b7d3e5061",      # the published agent bridge's mint
    "kY3mQp7Zt1BvLrN8xWc2",        # a Firestore auto-id
    "incog_notes",                 # somebody's hand-made record
    "incog_1_1",                   # prefix, but no real timestamp to expire on
    "xincog_1758400000000_1",      # not anchored at the front
    "incog_1758400000000_1-copy",  # not anchored at the end
    "incog_1758400000000_1234567",  # counter past the shape
    "",
])
def test_every_other_id_this_database_holds_is_an_ordinary_research(rid):
    """⛔⛔ ANCHORED AT BOTH ENDS. A bare `startswith("incog_")` would hang a
    48-hour fuse on `incog_notes` and hand `incog_1_1` to a TTL rule that
    expects a real timestamp — the argument the web's copy makes in its own
    header, held here because this file cannot import that one."""
    assert research._is_incognito_research(rid) is False


@pytest.mark.parametrize("rid", [None, 1758400000000, b"incog_1758400000000_1", object()])
def test_a_research_id_that_is_not_a_string_is_not_incognito(rid):
    """`meta.json`, `owner.json` and a Firestore document all reach this helper
    with whatever they happen to hold. `re.match` on a non-string raises, and a
    raise here is a machine that stops mid-sweep."""
    assert research._is_incognito_research(rid) is False


def test_the_helper_asks_its_argument_and_never_the_running_run(monkeypatch):
    """⛔ THE ACTIVE-RUN GLOBAL IS NOT AN INPUT. The start listener, the orphan
    sweep and boot recovery all touch OTHER people's records inside a process
    that has one `_fb_research_id` — a helper that read it would answer about
    the wrong run at every one of those sites."""
    monkeypatch.setattr(research, "_fb_research_id", "incog_1758400000000_1")
    assert research._is_incognito_research("chat_1758400000000_1") is False
    monkeypatch.setattr(research, "_fb_research_id", "chat_1758400000000_1")
    assert research._is_incognito_research("incog_1758400000000_1") is True


# ══ 2. the capability rides the device document, on both branches ═════════

def _installed(monkeypatch):
    monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.14")
    monkeypatch.setattr(research, "_serving_version", lambda: "0.1.14")
    monkeypatch.setattr(research, "_check_newer_version", lambda *, force=False: None)


def test_an_installed_wheel_publishes_the_capability(monkeypatch):
    _installed(monkeypatch)
    assert research._device_version_fields()["incognitoRuns"] == 1


def test_a_source_checkout_publishes_it_too(monkeypatch):
    """⛔⛔ THE BRANCH THAT MATTERS TODAY. The owner's own machine is a source
    checkout — it publishes `version: None`, which is why a version gate could
    never have done this job, and it is where the first incognito run is fired.
    The early return for that branch is a separate `return` statement, so it can
    be (and once was) forgotten."""
    monkeypatch.setattr(research, "_is_source_checkout", lambda: True)
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.14")
    fields = research._device_version_fields()
    assert fields["sourceCheckout"] is True and fields["version"] is None
    assert fields["incognitoRuns"] == 1


def test_the_capability_is_an_int_because_the_rules_type_check_it(monkeypatch):
    """`incognitoRunsWriteIsValid()` admits the key only as an int. A string
    "1" or a bool would fail `hasOnly`'s companion check and take the WHOLE
    throttled version patch down with it — version, servingVersion and the
    About row's update signal included."""
    _installed(monkeypatch)
    value = research._device_version_fields()["incognitoRuns"]
    assert type(value) is int


def test_nothing_else_about_the_published_fields_moved(monkeypatch):
    """⭐ THE NORMAL MACHINE IS UNCHANGED. One added key, and the four fields the
    app already reads answer exactly as before."""
    monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.13")
    monkeypatch.setattr(research, "_serving_version", lambda: "0.1.12")
    monkeypatch.setattr(research, "_check_newer_version", lambda *, force=False: "0.1.14")
    assert research._device_version_fields() == {
        "version": "0.1.13", "updateAvailable": "0.1.14", "sourceCheckout": False,
        "servingVersion": "0.1.12", "incognitoRuns": 1}


# ══ 3. the shape lives in four files that cannot import each other ════════

def _web() -> "Path | None":
    """The web repo: `SR_WEB_REPO` when set (a worktree layout), else the
    sibling checkout this repo's other parity tests read."""
    env = os.environ.get("SR_WEB_REPO")
    base = Path(env) if env else Path(__file__).resolve().parents[2] / "dg-research"
    return base if (base / "firestore.rules").exists() else None


def test_the_id_shape_agrees_with_every_copy_in_the_web_repo():
    """⛔⛔ FOUR COPIES, NO IMPORTS. `src/lib/incognito.ts` decides what the app
    filters, `firestore.rules` and `storage.rules` decide what the database
    refuses, and this file decides what the machine does. Change one and the
    four stop agreeing about which runs the product refuses to keep — and the
    disagreement is silent in every direction.

    The rules' copy is written without `^…$` because `matches()` is a
    whole-string match; the two regex copies carry the anchors because `.test()`
    and `re.search()` are not. So the pin compares the BODY."""
    web = _web()
    if web is None:
        pytest.skip("no web checkout beside this one; set SR_WEB_REPO")
    body = research._INCOGNITO_ID_RE.pattern.strip("^$")
    assert body == "incog_[0-9]{13}_[0-9]{1,6}"

    ts = (web / "src" / "lib" / "incognito.ts").read_text(encoding="utf-8")
    m = re.search(r"INCOGNITO_ID_RE\s*=\s*/(.+?)/;", ts)
    assert m, "the web's INCOGNITO_ID_RE moved — re-anchor this pin"
    assert m.group(1).strip("^$") == body, (
        "the app and the machine disagree about which ids keep nothing")

    for name in ("firestore.rules", "storage.rules"):
        text = (web / name).read_text(encoding="utf-8")
        found = re.findall(r"matches\('\^?(incog_[^']*?)\$?'\)", text)
        assert found, f"{name} no longer matches an incognito id — re-anchor"
        assert set(found) == {body}, f"{name} carries a different id shape: {found}"


def test_the_rules_admit_the_capability_key_the_machine_now_writes():
    """⛔ THE HOLD, MADE MECHANICAL. `hasOnly` refuses the whole device patch
    when one key is off-list, so this wheel's version update would 403 in full —
    version, servingVersion and the update signal with it — against a project
    whose rules have not been deployed. Against a web checkout without the key
    this FAILS, which is the signal that the deploy has not happened yet."""
    web = _web()
    if web is None:
        pytest.skip("no web checkout beside this one; set SR_WEB_REPO")
    text = (web / "firestore.rules").read_text(encoding="utf-8")
    assert "'incognitoRuns'" in text, (
        "incognitoRuns is not on the device key list — the version patch would "
        "be refused whole")
    assert re.search(r"request\.resource\.data\.get\('incognitoRuns',\s*0\)\s+is\s+int",
                     text), "the rules must type-check incognitoRuns as an int"
