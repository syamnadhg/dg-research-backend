"""The build label must name the code that RAN, not the package on disk.

⛔⛔ THE INCIDENT. On 2026-09-19 a machine executed source stamped 0.1.14 while
every log line, the run's `meta.json`, the support bundle's `index.json` and the
`X-Build` ingest header all said `build=0.1.13`. `_sr_version()` is
`importlib.metadata.version("superresearch")`, which answers from whatever
`*.dist-info` is discoverable on `sys.path` — a DIFFERENT ARTIFACT from the
module the interpreter loaded. An editable install (`pip install -e .`, which is
how this repo is set up) leaves the last built wheel's metadata sitting there
forever while the tree moves on.

I read that label and told the owner they had run a stale wheel. They said "I'm
confident we have used this code only" and they were right. The run was only
pinned to the real source by grepping emitted log strings that exist in no
earlier revision. A label that sends its reader to the wrong revision is worse
than no label at all, and it cost the whole diagnosis.

⭐ THIS CHECKOUT REPRODUCES IT RIGHT NOW, which is why the first test needs no
fixture: `pyproject.toml` says 0.1.14 and the dist-info beside it says 0.1.13.

⭐ AND THE ANSWER ALREADY EXISTED NEXT DOOR. `_is_source_checkout()` is a
path check that cannot be fooled by metadata, and `_device_version_fields()` had
ALREADY been forced to reach for it after the same trap bit the device document
("the VivobookPro bug", research.py). That lesson was learned once, for one
consumer, and never carried to the logging / support / telemetry path — which is
the only path this file is about. This is a port, not an invention.
"""
import re

import pytest

import research
from conftest import code_only


@pytest.fixture(autouse=True)
def _clear_label_cache():
    """The label is memoised for the life of the process — it is read on log
    lines and a `pyproject.toml` read per line is not free. Every test here
    changes an input to it, so the cache has to go both ways."""
    research._BUILD_LABEL_CACHE = None
    yield
    research._BUILD_LABEL_CACHE = None


# ── The incident, reproduced ──────────────────────────────────────────────

def test_this_very_checkout_is_the_bug():
    """⛔ No fixture, no mock. Run from the tree, the two numbers disagree, and
    that disagreement IS the defect. If this ever stops holding — someone
    reinstalled and the metadata caught up — the assertions below still carry
    the rule; this one just stops being able to show it for free."""
    assert research._is_source_checkout() is True
    tree = research._source_tree_version()
    assert re.match(r"^\d+\.\d+", tree), tree
    assert research._sr_build_label() == tree + "+src"


def test_the_label_never_borrows_the_installed_number_in_a_checkout():
    """⛔⛔ THE WHOLE POINT. Whatever metadata claims, a source run is labelled
    from the TREE."""
    research._BUILD_LABEL_CACHE = None
    label = research._sr_build_label()
    assert label.endswith("+src")
    assert label.split("+")[0] == research._source_tree_version()


def test_an_installed_build_is_labelled_from_its_metadata(monkeypatch):
    """The other case, and it must NOT grow a suffix: in a wheel the code and the
    metadata ship as one artifact and cannot disagree, so there is nothing to
    warn about."""
    monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
    monkeypatch.setattr(research, "_sr_version", lambda: "0.2.7")
    research._BUILD_LABEL_CACHE = None
    assert research._sr_build_label() == "0.2.7"
    assert research._is_src_build_label("0.2.7") is False


def test_a_checkout_with_no_readable_pyproject_says_so_rather_than_guessing(monkeypatch):
    """⛔ It must NOT fall back to `_sr_version()`. Borrowing the installed
    number when the tree cannot be read is the exact defect, arrived at by a
    different route."""
    monkeypatch.setattr(research, "_is_source_checkout", lambda: True)
    monkeypatch.setattr(research, "_source_tree_version", lambda: "")
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.13")
    research._BUILD_LABEL_CACHE = None
    label = research._sr_build_label()
    assert label == "(source checkout)"
    assert "0.1.13" not in label
    assert research._is_src_build_label(label) is True


@pytest.mark.parametrize("boom", ["_is_source_checkout", "_source_tree_version",
                                  "_sr_version"])
def test_it_never_raises_on_a_log_line(monkeypatch, boom):
    """This is called from inside log formatting. A throw here takes out the
    line it was decorating, and then the run."""
    def _raise():
        raise RuntimeError("no")
    monkeypatch.setattr(research, boom, _raise)
    research._BUILD_LABEL_CACHE = None
    assert isinstance(research._sr_build_label(), str)
    assert research._sr_build_label() != ""


def test_the_label_is_computed_once(monkeypatch):
    calls = []
    real = research._source_tree_version
    monkeypatch.setattr(research, "_source_tree_version",
                        lambda: (calls.append(1), real())[1])
    research._BUILD_LABEL_CACHE = None
    a = research._sr_build_label()
    b = research._sr_build_label()
    c = research._sr_build_label()
    assert a == b == c
    assert len(calls) == 1, f"pyproject.toml read {len(calls)} times"


# ── Every report ABOUT A RUN uses it ──────────────────────────────────────

def _research_code() -> str:
    with open(research.__file__, encoding="utf-8") as f:
        return code_only(f.read())


# The fields that were wrong in support bundle K6N8WMXZ, each as it appears in
# source. Comments are stripped first, so the prose above these lines — which
# quotes `_sr_version()` by name to explain what NOT to do — cannot satisfy them.
RUN_REPORT_SITES = [
    '"build": _sr_build_label(),',                 # run meta.json + bundle index
    'f"build={_sr_build_label()} pid=',            # the per-run log line
    'build={_sr_build_label()} pid=',              # the worker start line
    '"buildId", _sr_build_label()',                # the logBundles row
    '"X-Build": _sr_build_label(),',               # the ingest header
]


@pytest.mark.parametrize("frag", RUN_REPORT_SITES)
def test_the_run_report_fields_carry_the_build_label(frag):
    assert frag in _research_code(), frag


def test_no_run_report_field_reads_package_metadata_any_more():
    """⛔⛔ THE GUARD THAT OUTLIVES THIS FIX. `_sr_version()` is still correct for
    the UPDATE machinery, which genuinely asks "which distribution is installed"
    so it can compare against PyPI — so it cannot simply be deleted, and the next
    person adding a `build=` log line will reach for the name they see used
    elsewhere. These shapes are the ones that describe a RUN."""
    code = _research_code()
    banned = [
        '"build": _sr_version()',
        "build={_sr_version()}",
        '"buildId", _sr_version()',
        '"X-Build": _sr_version()',
    ]
    for b in banned:
        assert b not in code, f"a run report is back on package metadata: {b}"


def test_serving_version_is_not_mistaken_for_the_fix():
    """⛔ The near-miss that would ship as a no-op. `_BOOT_VERSION` is the SAME
    metadata read, merely frozen at import so a pipx upgrade cannot flip it
    mid-process. In the incident it answers 0.1.13 too."""
    src = _research_code()
    assert "_BOOT_VERSION: \"str | None\" = _sr_version()" in src, (
        "if _BOOT_VERSION changed source, re-check that it is still the "
        "installed-metadata read that _restart_pending compares against")


# ── The marker file and the restart nudge ─────────────────────────────────

def test_the_running_version_marker_records_both_numbers():
    """`version` stays the installed read because `_restart_pending` compares it;
    `build` is added so the file itself tells the truth about the process."""
    src = code_only(research._write_running_version)
    assert '"version": _sr_version()' in src
    assert '"build": _sr_build_label()' in src


def test_a_source_checkout_is_never_pending_a_restart():
    """⛔ A latent bug the fix would otherwise have created. There is no wheel to
    have landed in a checkout, and the old guard (`installed.startswith("(")`)
    is the near-dead branch — an editable install answers with a real number and
    sails straight past it."""
    assert research._is_source_checkout() is True
    assert research._restart_pending() is None
    assert "_is_source_checkout()" in code_only(research._restart_pending)


def test_the_restart_check_still_fires_for_a_real_installed_mismatch(monkeypatch):
    """The guard above must not have switched the whole check off — this is the
    case it exists to report."""
    monkeypatch.setattr(research, "_is_source_checkout", lambda: False)
    monkeypatch.setattr(research, "_running_version", lambda: "0.1.13")
    monkeypatch.setattr(research, "_sr_version", lambda: "0.1.14")
    assert research._restart_pending() == ("0.1.13", "0.1.14")


# ── The header the receiver truncates ─────────────────────────────────────

def test_the_build_label_fits_the_ingest_headers_32_char_cap():
    """`/api/logs/ingest` caps `x-build` at 32 characters and truncates SILENTLY.
    A label that overflowed would be corrupted on arrival with no error anywhere
    — the same class of quiet wrongness this whole file is about."""
    assert len(research._sr_build_label()) <= 32
    research._BUILD_LABEL_CACHE = None
