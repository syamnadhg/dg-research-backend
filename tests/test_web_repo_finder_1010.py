"""Every pin that reads the web app finds it ONE way, and says so when it cannot.

WHAT WAS WRONG (wave 10.10)

Eleven tests compare this machine with the web app's own files — its rules, its
telemetry catalogue, its send-logs contract, the regexes it renders sources with.
Eight of them looked in one place only: `parents[2] / "dg-research"`, the
directory holding THIS checkout. Every wave is built and gated in a worktree,
where that directory holds other worktrees, so those eight SKIPPED in the one
layout the gate actually runs in. The gate read `13 skipped`, nobody could say
which of them mattered, and the send-logs file's fake store did not even skip:
with no rules to parse it enforced nothing and every writer test passed.

Three files had grown better finders of their own, each slightly different, and
one of them did not honour `SR_WEB_REPO` at all.

WHAT HOLDS IT NOW

`tests/conftest.py` has the one finder: `SR_WEB_REPO` if set (a wrong value
FAILS), else the sibling checkout, else the sibling of the git common dir. This
file measures it twice over:

  * the finder itself, in both polarities, through a real git worktree;
  * ⛔⛔ every CONSUMER, run for real against webs built to be wrong in one way
    each. A consumer that goes back to building its own path cannot fail on a
    web this file hands it, so it cannot pass here. That is the pin — a tested
    finder that nothing calls is not a fix.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import conftest
import research
import test_bump_version as bump_t
import test_bundle_left_out_row_109 as bundle_t
import test_document_images_0913 as images_t
import test_numbered_sources_0918 as sources_t
import test_numbered_sources_placement_0918 as placement_t
import test_send_logs_command_0818 as send_logs_t
import test_telemetry_0818 as telemetry_t
import test_telemetry_call_sites_0818 as call_sites_t

REPO = Path(__file__).resolve().parents[1]


def _outcome(fn):
    """What a pin does when run: ("passed" | "skipped" | "failed", message).

    ⛔ Judged as a value, never with `pytest.raises(AssertionError)` alone: a
    skip is a BaseException, and one escaping from here would read as this
    file's own test being skipped — the silence this file exists to end."""
    try:
        fn()
    except pytest.skip.Exception as e:
        return "skipped", str(e)
    except (Exception, pytest.fail.Exception) as e:
        return "failed", f"{type(e).__name__}: {e}"
    return "passed", ""


def _web(tmp_path, files=None, name="dg-research"):
    """A web checkout: the marker file, plus exactly the files named."""
    web = tmp_path / name
    web.mkdir(parents=True)
    (web / "firestore.rules").write_text("rules_version = '2';\n", encoding="utf-8")
    for rel, body in (files or {}).items():
        (web / rel).parent.mkdir(parents=True, exist_ok=True)
        (web / rel).write_text(body, encoding="utf-8")
    return web


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", timeout=60)


# ══ 1. the finder ═════════════════════════════════════════════════════════════

def test_a_set_SR_WEB_REPO_is_the_answer(tmp_path, monkeypatch):
    web = _web(tmp_path)
    monkeypatch.setenv("SR_WEB_REPO", str(web))
    assert conftest.web_repo() == web
    assert conftest.web_repo_candidates() == [web]


def test_a_wrong_SR_WEB_REPO_fails_and_never_skips(tmp_path, monkeypatch):
    """⛔⛔ THE SILENCE THAT LOOKS LIKE A SWITCH-ON. Somebody sets the variable,
    mistypes it, and every cross-repo pin answers exactly what it answers when
    nobody set it — nothing."""
    monkeypatch.setenv("SR_WEB_REPO", str(tmp_path / "not-a-checkout"))
    kind, why = _outcome(conftest.web_repo)
    assert kind == "failed" and "not a dg-research checkout" in why, (kind, why)
    kind, why = _outcome(lambda: conftest.require_web_repo("x"))
    assert kind == "failed" and "not a dg-research checkout" in why, (kind, why)


def test_the_sibling_checkout_is_found_with_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SR_WEB_REPO", raising=False)
    here = tmp_path / "dg-research-backend"
    here.mkdir()
    web = _web(tmp_path)
    assert conftest.web_repo(here) == web


def test_a_directory_without_the_marker_is_not_a_web_checkout(tmp_path, monkeypatch):
    """The accept side above could be satisfied by a finder that returns the
    first candidate whatever it holds."""
    monkeypatch.delenv("SR_WEB_REPO", raising=False)
    here = tmp_path / "dg-research-backend"
    here.mkdir()
    (tmp_path / "dg-research").mkdir()
    assert conftest.web_repo(here) is None


def test_a_worktree_finds_the_web_beside_its_main_checkout(tmp_path, monkeypatch):
    """⛔⛔ THE LAYOUT EVERY WAVE IS GATED IN, driven through a REAL worktree.
    The sibling of a worktree is other worktrees; the web sits beside the MAIN
    checkout, which only the git common dir knows."""
    if shutil.which("git") is None:
        pytest.skip("⛔ no git on this machine — the worktree case was NOT measured")
    monkeypatch.delenv("SR_WEB_REPO", raising=False)
    home = tmp_path / "SuperResearch"
    main = home / "dg-research-backend"
    main.mkdir(parents=True)
    web = _web(home)
    (main / "research.py").write_text("# a checkout\n", encoding="utf-8")
    assert _git("init", "-q", "-b", "main", cwd=main).returncode == 0
    assert _git("add", "-A", cwd=main).returncode == 0
    assert _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                "-m", "one", "--no-gpg-sign", cwd=main).returncode == 0
    wt = tmp_path / "elsewhere" / "wt" / "a-branch"
    made = _git("worktree", "add", "-q", "-b", "side", str(wt), cwd=main)
    assert made.returncode == 0, made.stderr
    assert not (wt.parent / "dg-research").exists(), "the fixture proves nothing"

    assert conftest.web_repo(wt) == web
    assert conftest.sibling_web_checkouts(wt)[0] == wt.parent / "dg-research"


def test_nothing_on_disk_is_a_loud_skip_that_names_where_it_looked(tmp_path, monkeypatch):
    monkeypatch.delenv("SR_WEB_REPO", raising=False)
    nowhere = tmp_path / "nowhere" / "dg-research"
    monkeypatch.setattr(conftest, "sibling_web_checkouts", lambda here=None: [nowhere])
    assert conftest.web_repo() is None
    kind, why = _outcome(lambda: conftest.require_web_repo("the thing under test"))
    assert kind == "skipped", (kind, why)
    assert str(nowhere) in why and "the thing under test was NOT compared" in why, why


def test_a_found_web_missing_the_file_fails_rather_than_skips(tmp_path, monkeypatch):
    """Once a checkout IS found, a missing file is the web having moved what
    the pin compares — the drift itself, and never a reason to go quiet."""
    monkeypatch.setenv("SR_WEB_REPO", str(_web(tmp_path)))
    kind, why = _outcome(lambda: conftest.web_file("x", "src/lib/gone.ts"))
    assert kind == "failed" and "src/lib/gone.ts is missing" in why, (kind, why)
    monkeypatch.setenv("SR_WEB_REPO", str(_web(tmp_path / "b", {"src/lib/here.ts": "1"})))
    assert conftest.web_file("x", "src/lib/here.ts").read_text(encoding="utf-8") == "1"


# ══ 2. every consumer asks the finder ═════════════════════════════════════════
#
# ⭐ Each is RUN, against a web this file builds, three ways: nothing anywhere
# (it must skip, loudly), a web that disagrees (it must fail), and a mistyped
# `SR_WEB_REPO` (it must fail). A consumer that builds its own path answers the
# real disk instead, so it cannot produce all three.

CONSUMERS = {
    "send-logs: the fake store's rules": send_logs_t.test_the_fake_store_enforces_the_web_rules,
    "send-logs: the upload ceiling": send_logs_t.test_the_upload_ceiling_matches_the_storage_rule,
    "send-logs: the content type": send_logs_t.test_the_content_type_matches_the_storage_rule_too,
    "send-logs: the bundle contract":
        send_logs_t.TestRunCount().test_the_two_repos_agree_on_the_cap_and_the_action_names,
    "telemetry: the catalogue copy": telemetry_t.test_the_app_repo_carries_a_byte_identical_copy,
    "telemetry: the pairing route":
        call_sites_t.test_the_install_id_reaches_the_device_doc_at_pair_time,
    "sources: the web's token":
        sources_t.TestTheGrammarIsNotTheWebsToken().test_the_ported_token_is_still_the_literal_the_web_ships,
    "sources: the three web readers":
        placement_t.TestOurHeadingIsNotAResearchSlice()
        .test_the_three_web_readers_are_still_the_literals_this_file_ports,
    "bundle: the left-out counts": bundle_t.test_the_web_rules_allow_each_count_as_an_int,
    "images: the upload contract": images_t.test_the_reference_regex_is_the_webs,
}


@pytest.fixture()
def _at_repo_root(monkeypatch):
    # Several consumers read their local half by a path relative to the repo.
    monkeypatch.chdir(REPO)


@pytest.mark.parametrize("name", sorted(CONSUMERS))
def test_with_no_web_anywhere_each_consumer_skips_and_says_what_it_did_not_compare(
        name, tmp_path, monkeypatch, _at_repo_root):
    monkeypatch.delenv("SR_WEB_REPO", raising=False)
    nowhere = tmp_path / "nowhere" / "dg-research"
    monkeypatch.setattr(conftest, "sibling_web_checkouts", lambda here=None: [nowhere])
    kind, why = _outcome(CONSUMERS[name])
    assert kind == "skipped", f"{name}: {kind} {why}"
    assert "NOT compared" in why and str(nowhere) in why, f"{name}: {why}"


@pytest.mark.parametrize("name", sorted(CONSUMERS))
def test_against_a_web_without_its_file_each_consumer_fails(
        name, tmp_path, monkeypatch, _at_repo_root):
    monkeypatch.setenv("SR_WEB_REPO", str(_web(tmp_path)))
    kind, why = _outcome(CONSUMERS[name])
    assert kind == "failed", f"{name}: {kind} {why}"


@pytest.mark.parametrize("name", sorted(CONSUMERS))
def test_a_mistyped_SR_WEB_REPO_fails_each_consumer(name, tmp_path, monkeypatch, _at_repo_root):
    monkeypatch.setenv("SR_WEB_REPO", str(tmp_path / "typo"))
    kind, why = _outcome(CONSUMERS[name])
    assert kind == "failed" and "not a dg-research checkout" in why, f"{name}: {kind} {why}"


def _storage_rules(size_bytes, content_type):
    return ("match /logs/{userId} {\n"
            f"  allow write: if request.resource.size < {size_bytes} * 1 * 1\n"
            f"    && request.resource.contentType == '{content_type}';\n"
            "}\nmatch /{allPaths=**} {}\n")


@pytest.mark.parametrize("name, files", [
    ("telemetry: the catalogue copy", lambda: {
        "src/lib/telemetry-catalogue.json":
            (REPO / "telemetry_catalogue.json").read_text(encoding="utf-8")}),
    ("send-logs: the bundle contract", lambda: {
        "src/lib/bundle-contract.json":
            (REPO / "bundle-contract.json").read_text(encoding="utf-8")}),
    ("send-logs: the upload ceiling", lambda: {
        "storage.rules": _storage_rules(research.BUNDLE_UPLOAD_MAX_BYTES,
                                        research.BUNDLE_CONTENT_TYPE)}),
    ("sources: the web's token", lambda: {
        "src/lib/doc-sources.ts": "export const SOURCE_TOKEN_RE = /"
                                  + sources_t.WEB_MODEL_TOKEN_RE.pattern + "/g;\n"}),
])
def test_against_a_web_that_agrees_the_consumer_passes(
        name, files, tmp_path, monkeypatch, _at_repo_root):
    """⭐ THE ACCEPT SIDE. Without it, every refusal above is satisfied by a
    consumer that fails on everything."""
    monkeypatch.setenv("SR_WEB_REPO", str(_web(tmp_path, files())))
    kind, why = _outcome(CONSUMERS[name])
    assert kind == "passed", f"{name}: {kind} {why}"


def test_the_send_logs_fake_store_enforces_the_rules_of_the_web_it_was_handed(
        tmp_path, monkeypatch):
    """⛔⛔ THE CONSUMER THAT PASSED INSTEAD OF SKIPPING. The fake Firestore in
    the send-logs file parses its allowed keys out of the web's rules; with no
    rules it enforced nothing and every writer test in that file still passed.
    Keys nobody would ever ship prove it read THIS web's rules, and not the
    real disk's or none."""
    monkeypatch.setenv("SR_WEB_REPO", str(_web(tmp_path, {"firestore.rules": (
        "match /logBundles/{code} {\n"
        "  allow update: if request.resource.data.keys().hasOnly(['onlyThisKey']);\n"
        "  allow create: if request.resource.data.status == 'sentinelStatus';\n"
        "}\n// Researches\n")})))
    assert send_logs_t._rules_contract() == ({"onlyThisKey"}, "sentinelStatus")


def test_a_web_that_disagrees_by_one_value_fails_the_catalogue_copy(
        tmp_path, monkeypatch, _at_repo_root):
    """Same file, one event renamed — the drift the pin exists for."""
    ours = json.loads((REPO / "telemetry_catalogue.json").read_text(encoding="utf-8"))
    theirs = json.loads(json.dumps(ours))
    theirs["_renamed_by_this_test"] = True
    monkeypatch.setenv("SR_WEB_REPO", str(_web(tmp_path, {
        "src/lib/telemetry-catalogue.json": json.dumps(theirs)})))
    kind, why = _outcome(CONSUMERS["telemetry: the catalogue copy"])
    assert kind == "failed", (kind, why)


# ── the release tool's default: a LAYOUT pin, which asks only for the layout ──

def _layout(tmp_path, with_script=True):
    web = tmp_path / "SuperResearch" / "dg-research"
    (web / "scripts").mkdir(parents=True)
    if with_script:
        (web / "scripts" / "sync-agent-skill.mjs").write_text("//", encoding="utf-8")
    return web


def test_the_release_default_is_probed_against_the_layout_the_finder_answers(
        tmp_path, monkeypatch):
    """⛔ `SR_WEB_REPO` is deliberately not this pin's input, so it is driven by
    the layout list it DOES read. Both polarities: a layout holding the sync
    script passes, one without it fails, and none at all skips out loud."""
    monkeypatch.setenv("SR_WEB_REPO", str(tmp_path / "ignored-by-this-pin"))
    good = _layout(tmp_path / "a")
    monkeypatch.setattr(bump_t, "sibling_web_checkouts", lambda here=None: [good])
    assert _outcome(lambda: bump_t.test_the_real_checkout_is_found_with_NO_env_override(
        tmp_path, monkeypatch))[0] == "passed"

    bad = _layout(tmp_path / "b", with_script=False)
    monkeypatch.setattr(bump_t, "sibling_web_checkouts", lambda here=None: [bad])
    assert _outcome(lambda: bump_t.test_the_real_checkout_is_found_with_NO_env_override(
        tmp_path, monkeypatch))[0] == "failed"

    gone = tmp_path / "c" / "dg-research"
    monkeypatch.setattr(bump_t, "sibling_web_checkouts", lambda here=None: [gone])
    kind, why = _outcome(lambda: bump_t.test_the_real_checkout_is_found_with_NO_env_override(
        tmp_path, monkeypatch))
    assert kind == "skipped" and str(gone) in why and "NOT probed" in why, (kind, why)


# ══ 3. and nothing new builds its own path ════════════════════════════════════

#: `Path(__file__).resolve().parents[N] / "dg-research"`, on one line or two.
OWN_PATH = re.compile(r"__file__\)\.resolve\(\)\s*\.parents?\b[^\n]*(?:\n[^\n]*)?"
                      r"/\s*\"dg-research\"")


def test_no_test_file_builds_its_own_path_to_the_web_checkout():
    """⛔ The sweep that keeps the list above complete. A new cross-repo pin
    that reaches `parents[N] / "dg-research"` itself is blind in a worktree the
    day it lands, and nothing else here would notice it exists.

    ⚠ A SOURCE sweep on purpose, and the one place in this file that reads
    text: the property is "no other file carries its own finder", which is a
    fact about the tree rather than about any behaviour a run could show."""
    offenders = []
    for path in sorted((REPO / "tests").glob("*.py")):
        if path.name in ("conftest.py", Path(__file__).name):
            continue    # the finder itself, and this file's own probe text
        text = path.read_text(encoding="utf-8")
        for m in OWN_PATH.finditer(text):
            offenders.append(f"{path.name}:{text.count(chr(10), 0, m.start()) + 1}")
    assert not offenders, (
        "these build their own path to the web checkout — use conftest's "
        "web_file / require_web_repo instead: " + ", ".join(offenders))


def test_the_sweep_can_see_the_shape_it_hunts():
    """The sweep above passes trivially if its pattern matches nothing at all.
    Both shapes this repo actually had: one line, and split across two."""
    probe = ('    x = (Path(__file__).resolve().parents[2]\n'
             '         / "dg-research" / "src")\n'
             '    y = Path(__file__).resolve().parents[2] / "dg-research" / "a"\n'
             '    z = Path(__file__).resolve().parents[2] / "dg-research-backend"\n')
    assert len(OWN_PATH.findall(probe)) == 2
