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
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import research
from conftest import require_web_repo, web_repo_candidates


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
    # ⛔ A TRAILING NEWLINE. Python's `$` matches just before one, so `.match`
    # said yes where the app's `RegExp.test` and both rules' `matches()` say
    # no — the machine would fuse, purge and silence a research the app lists.
    "incog_1758400000000_1\n",
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

#: The web file that says the wave's web half is in a checkout at all.
_HALF = Path("src") / "lib" / "incognito.ts"


def _web() -> Path:
    """The web checkout these pins hold the machine against.

    ⭐ FOUND BY conftest's ONE FINDER (wave 10.10). This file grew the good
    version of it first — the git common dir, and a mistyped `SR_WEB_REPO` as a
    FAILURE rather than a skip — and it now lives in `tests/conftest.py` so
    every cross-repo pin in the suite gets both. The worktree case and the
    mistyped-path case are still driven from this file, below.

    ⛔ NO SKIP OF ITS OWN ANY MORE (wave 10.10 repair). It used to skip when
    the checkout it found had no `src/lib/incognito.ts`, on the grounds that
    the web half of wave 10.9 had not merged — true once, false since 10.9
    shipped it. So a gate aimed on purpose at a wrong or older checkout read
    these two pins as "skipped", the only mechanical check that the four
    copies agree. Now it follows the finder's rule, like every other
    cross-repo pin: once a checkout is found, a missing file FAILS, and
    `_web_text` says which one."""
    return require_web_repo("the four copies of the incognito id shape")


def _web_text(web: Path, rel: str) -> str:
    """One of the web's copies, or a sentence saying which one moved.

    ⛔ `read_text` straight off the path raised a bare `FileNotFoundError`,
    which reads as a broken test rather than as the finding it is: a checkout
    whose half of this wave is only partly there."""
    path = web / rel
    assert path.exists(), (
        f"{rel} is missing from {web} — this pin holds four copies of one id "
        f"shape together and cannot do it without that file; re-anchor it if "
        f"the web moved the file")
    return path.read_text(encoding="utf-8")


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
    body = research._INCOGNITO_ID_RE.pattern.strip("^$")
    assert body == "incog_[0-9]{13}_[0-9]{1,6}"

    ts = _web_text(web, str(_HALF))
    m = re.search(r"INCOGNITO_ID_RE\s*=\s*/(.+?)/;", ts)
    assert m, f"the web's INCOGNITO_ID_RE moved in {web} — re-anchor this pin"
    assert m.group(1).strip("^$") == body, (
        f"the app and the machine disagree about which ids keep nothing: "
        f"{m.group(1)!r} in {web} vs {research._INCOGNITO_ID_RE.pattern!r} here")

    for name in ("firestore.rules", "storage.rules"):
        text = _web_text(web, name)
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
    text = _web_text(web, "firestore.rules")
    assert "'incognitoRuns'" in text, (
        "incognitoRuns is not on the device key list — the version patch would "
        "be refused whole")
    assert re.search(r"request\.resource\.data\.get\('incognitoRuns',\s*0\)\s+is\s+int",
                     text), "the rules must type-check incognitoRuns as an int"


# ══ 4. the two pins above, measured ═══════════════════════════════════════
#
# ⛔⛔ A CROSS-REPO PIN IS THE EASIEST KIND TO LOSE. It reaches outside the
# checkout, so the ordinary way it fails is by finding nothing and saying
# nothing — and in the worktree this branch is built in, that is exactly what
# both of them did: `20 passed, 2 skipped`, with the only mechanical agreement
# between the machine, the app and both rules files silently unchecked.
#
# ⭐ So the pins are DRIVEN here, against synthetic web checkouts built to be
# wrong in one way each. Nothing about this reads source text for a name: every
# assertion below runs the real pin and judges what it raises.

_TS_OK = ('export const INCOGNITO_ID_RE = /^incog_[0-9]{13}_[0-9]{1,6}$/;\n')
_RULES_OK = (
    "function isIncognitoResearch(researchId) {\n"
    "  return researchId.matches('^incog_[0-9]{13}_[0-9]{1,6}$');\n"
    "}\n"
    "hasOnly(['version', 'updateAvailable', 'incognitoRuns'])\n"
    "request.resource.data.get('incognitoRuns', 0) is int\n")
_STORAGE_OK = "return researchId.matches('^incog_[0-9]{13}_[0-9]{1,6}$');\n"


def _fake_web(tmp_path, *, ts=_TS_OK, rules=_RULES_OK, storage=_STORAGE_OK):
    """A web checkout with exactly the three files these pins read — any of
    which can be left out (`None`) or made to disagree."""
    web = tmp_path / "dg-research"
    (web / "src" / "lib").mkdir(parents=True)
    for rel, body in ((_HALF, ts), (Path("firestore.rules"), rules),
                      (Path("storage.rules"), storage)):
        if body is not None:
            (web / rel).write_text(body, encoding="utf-8")
    return web


def _raised(fn):
    """What the pin raises, whatever kind of thing it is.

    ⛔ `pytest.raises(AssertionError)` alone would let a `Skipped` through as an
    ERROR in the report — and a skip escaping from here would also trip the
    mutation harness's own "the parity pins SKIPPED" guard, which aborts the
    whole run. So every outcome is caught and judged as a value."""
    with pytest.raises(BaseException) as err:   # noqa: PT011 — the point is the type
        fn()
    return err.value


def test_both_pins_run_and_pass_against_a_web_checkout_that_agrees(
        tmp_path, monkeypatch):
    """⭐ ACCEPT POLARITY, and the one that proves `SR_WEB_REPO` is honoured:
    without it every refusal below is satisfied by a pin that raises at
    everything."""
    monkeypatch.setenv("SR_WEB_REPO", str(_fake_web(tmp_path)))
    test_the_id_shape_agrees_with_every_copy_in_the_web_repo()
    test_the_rules_admit_the_capability_key_the_machine_now_writes()


def test_a_web_copy_that_disagrees_is_named_on_both_sides(tmp_path, monkeypatch):
    """⛔⛔ THE WHOLE POINT OF THE PIN. The counter bound widens in the app and
    nowhere else, so a seven-digit id is ephemeral to the browser and ordinary
    to the machine, the rules and the sweep."""
    web = _fake_web(tmp_path, ts="export const INCOGNITO_ID_RE = "
                                 "/^incog_[0-9]{13}_[0-9]{1,7}$/;\n")
    monkeypatch.setenv("SR_WEB_REPO", str(web))
    err = _raised(test_the_id_shape_agrees_with_every_copy_in_the_web_repo)
    assert isinstance(err, AssertionError), f"answered {err!r}"
    assert "{1,7}" in str(err) and "{1,6}" in str(err), (
        f"the reader is not told which two shapes disagree: {err}")


def test_a_rules_file_the_web_moved_is_a_sentence_not_a_traceback(
        tmp_path, monkeypatch):
    """⛔⛔ THE BARE `FileNotFoundError`. Against a real sibling checkout whose
    web half has not landed, this pin died on `read_text` — a stack trace about
    pathlib, in the one place a reader needs to be told that the app and the
    machine could not be compared at all."""
    monkeypatch.setenv("SR_WEB_REPO", str(_fake_web(tmp_path, storage=None)))
    err = _raised(test_the_id_shape_agrees_with_every_copy_in_the_web_repo)
    assert isinstance(err, AssertionError), (
        f"a missing web file answered {type(err).__name__}: {err}")
    assert "storage.rules" in str(err), str(err)


def test_a_web_checkout_without_the_capability_key_fails_loudly(
        tmp_path, monkeypatch):
    """The deploy signal: rules without the key would 403 the WHOLE version
    patch, so this must be a failure and never a quiet pass."""
    monkeypatch.setenv("SR_WEB_REPO", str(_fake_web(
        tmp_path, rules="function isIncognitoResearch(researchId) {\n"
                        "  return researchId.matches("
                        "'^incog_[0-9]{13}_[0-9]{1,6}$');\n}\n")))
    err = _raised(test_the_rules_admit_the_capability_key_the_machine_now_writes)
    assert isinstance(err, AssertionError), f"answered {err!r}"
    assert "device key list" in str(err), str(err)


@pytest.mark.parametrize("pin", [
    test_the_id_shape_agrees_with_every_copy_in_the_web_repo,
    test_the_rules_admit_the_capability_key_the_machine_now_writes,
])
def test_an_SR_WEB_REPO_that_is_not_a_web_checkout_is_never_a_skip(
        tmp_path, monkeypatch, pin):
    """⛔⛔ THE SILENCE THAT LOOKS LIKE A SWITCH-ON. Somebody sets the variable,
    mistypes the path, and the pins answer exactly what they answer when nobody
    set it at all — nothing. A path that was named explicitly is a claim, and a
    claim this pin cannot honour has to be loud."""
    monkeypatch.setenv("SR_WEB_REPO", str(tmp_path / "not-a-checkout"))
    err = _raised(pin)
    assert isinstance(err, AssertionError), (
        f"a mistyped SR_WEB_REPO answered {type(err).__name__} — a skip here "
        f"is the defect: {err}")
    assert "not a dg-research checkout" in str(err), str(err)


def test_a_named_checkout_without_the_webs_copy_fails_never_skips(
        tmp_path, monkeypatch):
    """⛔⛔ A NAMED-BUT-WRONG CHECKOUT (cross-verify, wave 10.10). It has the
    rules file, so the finder accepts it, but not `src/lib/incognito.ts`: an
    older checkout, or the wrong one. The id-shape pin used to SKIP there with
    "the web half of this wave has not merged yet", which stopped being true
    when wave 10.9 shipped that file — so a gate aimed at the wrong checkout
    read the only mechanical check of the four copies as skipped. It fails,
    and says which file is missing where."""
    web = _fake_web(tmp_path, ts=None)
    monkeypatch.setenv("SR_WEB_REPO", str(web))
    err = _raised(test_the_id_shape_agrees_with_every_copy_in_the_web_repo)
    assert isinstance(err, AssertionError), (
        f"a named checkout without incognito.ts answered {type(err).__name__} — "
        f"a skip here is the defect: {err}")
    assert str(web) in str(err) and "incognito.ts" in str(err), str(err)
    # …and the rules pin, which never reads that file, still judges the rules.
    test_the_rules_admit_the_capability_key_the_machine_now_writes()


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", timeout=60)


def test_a_worktree_looks_past_its_own_parent_for_the_web_repo(tmp_path,
                                                               monkeypatch):
    """⛔⛔ THE SKIP THAT COST THIS ITEM ITS ONLY CROSS-REPO CHECK, driven
    through a REAL worktree rather than described.

    With no `SR_WEB_REPO` the resolver used to offer exactly one candidate —
    the directory holding the backend — and in a worktree that directory holds
    other worktrees and no checkout at all. Every wave of this branch was built
    and gated in one, so both parity pins skipped every single time.

    ⭐ A synthetic tree is the only way to measure this without asserting facts
    about the machine the suite happens to run on: `git worktree` is set up for
    real, and the sibling the resolver must reach sits beside the MAIN
    checkout, two directories away from where the worktree lives."""
    if shutil.which("git") is None:
        pytest.skip("no git on this machine — the worktree resolution was NOT "
                    "measured")
    monkeypatch.delenv("SR_WEB_REPO", raising=False)
    home = tmp_path / "SuperResearch"
    main = home / "dg-research-backend"
    (main / "tests").mkdir(parents=True)
    (home / "dg-research" / "src" / "lib").mkdir(parents=True)
    (main / "research.py").write_text("# a checkout\n", encoding="utf-8")
    assert _git("init", "-q", "-b", "main", cwd=main).returncode == 0
    assert _git("add", "-A", cwd=main).returncode == 0
    assert _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                "-m", "one", "--no-gpg-sign", cwd=main).returncode == 0
    wt = tmp_path / "elsewhere" / "wt" / "a-branch"
    made = _git("worktree", "add", "-q", "-b", "side", str(wt), cwd=main)
    assert made.returncode == 0, made.stderr

    candidates = web_repo_candidates(wt)
    assert home / "dg-research" in candidates, (
        f"a worktree found nowhere to look but its own parent: {candidates}")
    assert not (wt.parent / "dg-research").exists(), (
        "the parent candidate exists in this fixture, so reaching the sibling "
        "proves nothing")
