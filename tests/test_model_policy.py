"""P2 model POLICY — family-only selection, learned known-good, probe cadence.

Rewritten 2026-08-01 for the owner directive "only model family is gonna be
there and both dom and CUA (fallback) must auto heal on every model release".
These previously pinned a version FLOOR (claude 4.8 / gemini 3.5) and the
"4.8"/"4.7"/"4" prompt tokens rendered from it. Both are gone: there is no
version literal in the policy, the picker takes the highest offered member of
the family, and never-downgrade is a LEARNED known-good used only as a
step-back target.

Dep-free: imports only `models` (no research.py / playwright).
"""
import json
import tempfile
from pathlib import Path

import models

# A scratch dir for the two overlay tests that cannot use the tmp_path fixture
# (they loop over several payloads and restore the path themselves).
_MP_TMP = Path(tempfile.mkdtemp(prefix="model-policy-"))


# ── The one rule the whole change rests on ────────────────────────────────

def test_policy_carries_no_version_number_anywhere():
    """The regression guard for the entire directive. A version reintroduced
    into the policy — as a floor, a default, or a label — rots on the next
    release and drags every prompt and picker that derives from it along."""
    blob = json.dumps(models.P2_MODEL_POLICY) + json.dumps(models.P1_MODEL_POLICY)
    assert not any(ch.isdigit() for ch in blob), (
        f"a version number crept back into the model policy: {blob}"
    )


def test_floor_key_is_gone_from_every_platform():
    """Named explicitly so a merge that restores `floor` fails loudly rather
    than silently re-arming the stranding bug (a floor made `model_ok` true on
    an already-acceptable model, so the picker never opened and the account sat
    on its current version through a whole release cycle)."""
    for platform, pol in models.P2_MODEL_POLICY.items():
        assert "floor" not in pol, f"{platform} still carries a version floor"
    assert not hasattr(models, "p2_floor"), (
        "p2_floor() must not exist — selection is family + highest-offered"
    )


def test_version_render_helpers_are_gone():
    """These existed only to splice '4.8'/'4.7'/'4' into prompts."""
    for name in ("p2_claude_ver", "p2_claude_prev_ver", "p2_claude_major"):
        assert not hasattr(models, name), f"{name} must not exist"


def test_family_accessor_returns_the_family_word():
    assert models.p2_family("claude") == "opus"
    assert models.p2_family("gemini") == "flash"
    assert models.p2_family("chatgpt") == ""      # no model lever
    assert models.p2_family("nonexistent") == ""


# ── The CUA setup directive ───────────────────────────────────────────────

def test_claude_setup_directive_is_derived_from_policy():
    d = models.p2_claude_setup_directive()
    fam = models.P2_MODEL_POLICY["claude"]["family"].capitalize()
    effort = models.P2_MODEL_POLICY["claude"]["effort"].capitalize()
    tool = models.P2_MODEL_POLICY["claude"]["tool"].capitalize()
    assert fam in d, "the family must come from the policy"
    assert f"{effort} effort" in d, "the effort label must come from the policy"
    assert f"{tool} tool" in d


def test_claude_setup_directive_names_no_version():
    """Naming ANY version — even one derived from a policy value — is what made
    a HIGHER model read as wrong, sending the agent into the model menu on an
    account that was already correct ('the selector opens twice')."""
    d = models.p2_claude_setup_directive()
    assert not any(ch.isdigit() for ch in d), f"a version leaked into: {d!r}"
    assert "VERSION NUMBER DOES NOT MATTER" in d


def test_claude_setup_directive_keeps_an_upgrade_lever():
    """⚠ This string runs ONLY after the DOM path FAILED. Telling the agent to
    leave the model alone here — the rule the VALIDATE string correctly uses —
    would remove the last way an account gets upgraded when the DOM selectors
    have rotted, since the periodic probe lives in the DOM path that just died."""
    d = models.p2_claude_setup_directive()
    low = d.lower()
    assert "highest" in low, "the fallback must still pick the newest offered"
    assert "open the model menu" in low, (
        "the fallback path must be allowed to open the menu — that is the whole "
        "point of a fallback that fires because the DOM path could not"
    )
    # …but it must not re-click a model that is already the highest.
    assert "without clicking" in low, (
        "re-clicking the already-selected model is the #744 loop"
    )


def test_claude_setup_directive_no_longer_asks_for_a_thinking_toggle():
    """Opus 5 removed it. Asking for a control that cannot be found is what made
    the DOM path fail every run and hand over to CUA."""
    d = models.p2_claude_setup_directive().lower()
    assert "thinking" not in d


def test_labels_carry_the_thinking_and_tool_policy():
    claude = models.p2_labels("claude")
    assert claude["effort"] == "max"
    # FALSE on purpose since 2026-07-30: Opus 5 dropped the separate Thinking
    # toggle that Opus 4.x carried inside the Effort submenu — effort IS the
    # reasoning lever there now. While this was True, setup opened the model
    # popover on every run purely to reach a control that no longer exists.
    # Flipping it back must reopen that path, which test_claude_popover_skip.py
    # pins behaviourally.
    assert claude["thinking"] is False
    assert claude["tool"] == "research"
    gemini = models.p2_labels("gemini")
    assert gemini["thinking"] == "extended"   # Gemini still has one
    assert "pro" in gemini["reject"] and "lite*" in gemini["reject"]


# ── Overlay: reads, kill-switch, corruption ───────────────────────────────

def _arm(monkeypatch, tmp_path, payload, *, on=True):
    """Point the overlay at a temp file with `payload` (None = no file) and set
    the kill-switch via the ENV VAR — the flag is a live read now, so a test can
    flip it the same way an operator does."""
    p = tmp_path / "model_refresh.json"
    if payload is not None:
        p.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("DG_MODEL_REFRESH_ENABLED", "1" if on else "0")
    monkeypatch.setattr(models, "_MODEL_REFRESH_OVERLAY_PATH", p)
    return p


def test_kill_switch_defaults_on():
    """It shipped OFF, which meant nothing was ever learned and the fallback
    machinery was dead code. With the floor literals gone the learned
    known-good IS the fallback, so the default had to flip."""
    assert models.model_refresh_enabled() is True


def test_kill_switch_is_a_live_env_read(monkeypatch):
    """It used to be a module constant evaluated at import: setting the env var
    did nothing until the daemon restarted, and a test had to reach in and
    monkeypatch the constant."""
    monkeypatch.setenv("DG_MODEL_REFRESH_ENABLED", "0")
    assert models.model_refresh_enabled() is False
    monkeypatch.setenv("DG_MODEL_REFRESH_ENABLED", "1")
    assert models.model_refresh_enabled() is True


def test_overlay_ignored_when_flag_off(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, {"claude": {"known_good": 4.8}}, on=False)
    assert models.p2_known_good("claude") is None


def test_known_good_from_overlay_when_armed(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, {"claude": {"known_good": 4.8}})
    assert models.p2_known_good("claude") == 4.8


def test_corrupt_overlay_falls_back_to_defaults(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, "{ this is not valid json :::")
    assert models.p2_known_good("claude") is None
    assert models.p2_labels("claude")["family"] == "opus"


def test_missing_overlay_falls_back_to_defaults(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)  # no file on disk
    assert models.p2_known_good("claude") is None


def test_non_dict_overlay_is_rejected(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, "[1, 2, 3]")  # valid json, wrong shape
    assert models.p2_labels("claude")["family"] == "opus"


# ── Overlay label merge is WHITELISTED ────────────────────────────────────
# It used to dict.update() straight from the file. With the kill-switch now ON
# by default, any stale or hand-edited overlay on a user's box would otherwise
# become live config on every run.

def test_overlay_may_override_a_known_label(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, {"claude": {"labels": {"effort": "high"}}})
    assert models.p2_labels("claude")["effort"] == "high"


def test_overlay_cannot_inject_an_unknown_key(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, {"claude": {"labels": {"floor": 9.9, "evil": True}}})
    merged = models.p2_labels("claude")
    assert "floor" not in merged, "a floor must not be injectable through the overlay"
    assert "evil" not in merged


def test_overlay_cannot_set_a_label_to_the_wrong_type(monkeypatch, tmp_path):
    """`thinking: true` from a stale file would re-arm the every-run popover
    hunt for a control Opus 5 removed; a non-string `effort` would break the
    trigger read that lets setup skip the popover at all."""
    _arm(monkeypatch, tmp_path, {"claude": {"labels": {"effort": 5, "family": ["opus"]}}})
    merged = models.p2_labels("claude")
    assert merged["effort"] == "max", "a wrong-typed override must lose to the code default"
    assert merged["family"] == "opus"


def test_overlay_thinking_accepts_bool_or_string(monkeypatch, tmp_path):
    # claude uses a bool, gemini uses the string "extended" — both are legal.
    _arm(monkeypatch, tmp_path, {"claude": {"labels": {"thinking": True}},
                                 "gemini": {"labels": {"thinking": "standard"}}})
    assert models.p2_labels("claude")["thinking"] is True
    assert models.p2_labels("gemini")["thinking"] == "standard"


# ── record_known_good: the step-back target, never a floor ────────────────

def test_record_known_good_is_noop_when_flag_off(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None, on=False)
    assert models.record_known_good("claude", 4.8) is False


def test_record_known_good_writes_and_reads_back_as_float(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)
    assert models.record_known_good("claude", 4.8) is True
    assert models.p2_known_good("claude") == 4.8
    assert isinstance(models.p2_known_good("claude"), float)


def test_record_known_good_only_writes_on_change(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)
    assert models.record_known_good("claude", 4.8) is True
    assert models.record_known_good("claude", 4.8) is False  # unchanged → no churn
    assert models.record_known_good("claude", 5.0) is True   # advanced → write


def test_record_known_good_rejects_junk(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)
    assert models.record_known_good("claude", None) is False
    assert models.record_known_good("claude", "abc") is False
    assert models.record_known_good("claude", -1) is False
    assert models.record_known_good("claude", 0) is False


def test_record_known_good_preserves_other_platforms(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)
    models.record_known_good("claude", 4.8)
    models.record_known_good("gemini", 3.5)
    assert models.p2_known_good("claude") == 4.8
    assert models.p2_known_good("gemini") == 3.5


def test_p2_known_good_coerces_string_overlay_value(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, {"claude": {"known_good": "4.8"}})
    assert models.p2_known_good("claude") == 4.8
    _arm(monkeypatch, tmp_path, {"claude": {"known_good": "nope"}})
    assert models.p2_known_good("claude") is None


def test_learning_a_value_does_not_create_a_floor(monkeypatch, tmp_path):
    """The contract that keeps a learned value from stranding a run: recording
    a known-good must not feed anything the picker consults. Reading it back is
    the ONLY way it can be used, and only the step-back caller does that."""
    _arm(monkeypatch, tmp_path, None)
    models.record_known_good("claude", 5.0)
    # An account offered only an older model must still be pickable: the ranker
    # is asked for the highest offered, with no lower bound of any kind.
    best = models.pick_highest_model(["Opus 4.8", "Sonnet 4.6"], "opus")
    assert best is not None and best["version"] == 4.8


# ── The probe cadence ─────────────────────────────────────────────────────

def test_probe_is_due_when_never_probed(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)
    assert models.model_probe_due("claude") is True


def test_probe_is_not_due_right_after_one(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)
    assert models.record_probe("claude", saw_menu=True) is True
    assert models.model_probe_due("claude") is False


def test_probe_becomes_due_again_after_the_interval(monkeypatch, tmp_path):
    import time
    _arm(monkeypatch, tmp_path, None)
    models.record_probe("claude", saw_menu=True)
    assert models.model_probe_due("claude") is False
    # Age the stamp past the window rather than sleeping.
    stale = time.time() - (models.model_probe_days() * 86400.0) - 60
    (tmp_path / "model_refresh.json").write_text(
        json.dumps({"claude": {"last_probe": stale}}), encoding="utf-8")
    assert models.model_probe_due("claude") is True


def test_probe_is_stamped_even_when_the_menu_was_never_seen(monkeypatch, tmp_path):
    """⚠ THE CADENCE'S SAFETY PROPERTY. Stamping only on a successful read would
    leave the probe permanently due the moment the popover markup rotates —
    re-opening the model menu on EVERY run, which is the #744 behaviour. The
    attempt is what bounds the cost."""
    _arm(monkeypatch, tmp_path, None)
    assert models.record_probe("claude", saw_menu=False) is True
    assert models.model_probe_due("claude") is False


def test_probe_is_never_due_when_the_kill_switch_is_off(monkeypatch, tmp_path):
    """⛔ THE INVERSION THIS GUARDS AGAINST. With the flag off nothing can be
    read or written, so `last_probe` is permanently absent — a naive "no stamp
    means due" would make the OFF switch open the popover on every single run,
    the exact opposite of what an operator asking for OFF wants."""
    _arm(monkeypatch, tmp_path, None, on=False)
    assert models.model_probe_due("claude") is False
    # …and it stays false no matter how many runs go by with no stamp.
    assert models.record_probe("claude", saw_menu=True) is False
    assert models.model_probe_due("claude") is False


def test_probe_due_on_a_junk_stamp(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, {"claude": {"last_probe": "yesterday"}})
    assert models.model_probe_due("claude") is True


def test_probe_days_is_a_live_env_read(monkeypatch):
    monkeypatch.setenv("DG_MODEL_PROBE_DAYS", "3")
    assert models.model_probe_days() == 3.0
    monkeypatch.setenv("DG_MODEL_PROBE_DAYS", "junk")
    assert models.model_probe_days() == 7.0
    monkeypatch.setenv("DG_MODEL_PROBE_DAYS", "0")
    assert models.model_probe_days() == 7.0     # 0 would mean "probe every run"


def test_probe_and_known_good_share_the_file_without_clobbering(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path, None)
    models.record_known_good("claude", 5.0)
    models.record_probe("claude", saw_menu=True)
    models.record_known_good("gemini", 3.5)
    assert models.p2_known_good("claude") == 5.0
    assert models.p2_known_good("gemini") == 3.5
    assert models.model_probe_due("claude") is False


def test_overlay_temp_file_is_per_process(monkeypatch, tmp_path):
    """A fixed temp name lets two processes interleave partial writes and
    os.replace() a torn document into place — which the reader then discards,
    silently wiping every learned value. Under the old design a code floor
    absorbed that; now the overlay IS the state."""
    import inspect
    src = inspect.getsource(models._write_model_refresh_overlay)
    assert "os.getpid()" in src, "the overlay temp file must carry the PID"


# ── parse_family_version / has_family / pick_highest_model ────────────────

def test_parse_family_version_handles_concatenated_row_text():
    assert models.parse_family_version("3.5 FlashAll-around help", "flash") == 3.5
    assert models.parse_family_version("Gemini 4.0 Flash · fast", "flash") == 4.0
    assert models.parse_family_version("Opus 4.8 Max", "opus") == 4.8
    assert models.parse_family_version("Sonnet 4.6", "opus") is None
    assert models.parse_family_version("", "flash") is None


def test_has_family_matches_with_or_without_a_version():
    assert models.has_family("Opus 5 Max", "opus") is True
    assert models.has_family("Opus Max", "opus") is True      # version-less rename
    assert models.has_family("opus", "opus") is True
    assert models.has_family("Sonnet 4.6", "opus") is False
    assert models.has_family("", "opus") is False
    assert models.has_family("Opus 5", "") is False


def test_pick_highest_flash_picks_the_newest():
    rows = ["3.1 Flash — fast", "3.5 FlashAll-around help", "2.0 Flash"]
    best = models.pick_highest_model(rows, "flash", reject=["lite", "deep think", "pro"])
    assert best["version"] == 3.5 and best["index"] == 1


def test_pick_highest_flash_rejects_siblings():
    rows = ["4.0 Flash-Lite", "3.5 Flash", "4.2 Pro", "5.0 Deep Think"]
    best = models.pick_highest_model(rows, "flash", reject=["lite", "deep think", "pro"])
    assert best["version"] == 3.5, "Lite/Pro/Deep-Think must be rejected before ranking"


def test_pick_highest_takes_the_newest_even_when_ancient_rows_exist():
    """The floor's old job, done structurally: the highest offered can never be
    a downgrade, so nothing has to be excluded by version."""
    rows = ["Opus 3.0", "Opus 4.8", "Opus 6.1", "Opus 4.0"]
    best = models.pick_highest_model(rows, "opus")
    assert best["version"] == 6.1


def test_pick_highest_tie_breaks_to_shortest_label():
    rows = ["3.5 Flash — the all-around helper with a long description", "3.5 Flash"]
    best = models.pick_highest_model(rows, "flash", reject=[])
    assert best["index"] == 1, "prefer the leaf row over a wrapper"


def test_pick_highest_reject_boundary_before_only():
    rows = ["3.5 Flash elite tier", "3.1 Flash"]
    best = models.pick_highest_model(rows, "flash", reject=["lite*"])
    assert best["version"] == 3.5, "'elite' must not false-reject on 'lite'"


def test_pick_highest_rejects_glued_sibling():
    rows = ["3.1 flash-litefastest answers", "3.0 Flash"]
    best = models.pick_highest_model(rows, "flash", reject=["lite*"])
    assert best["version"] == 3.0


def test_pick_highest_opus_family():
    rows = ["Opus 4.8 Max", "Sonnet 4.6", "Opus 5"]
    best = models.pick_highest_model(rows, "opus", reject=[])
    assert best["version"] == 5.0


def test_pick_highest_none_when_no_candidate():
    assert models.pick_highest_model([], "flash") is None
    assert models.pick_highest_model([None, "", "Ask Gemini"], "flash") is None


def test_pick_highest_accepts_a_version_less_family_row_as_last_resort():
    """The day a platform ships 'Opus' with no number, a version-only picker
    reports an empty menu and the run dies. It must still select something —
    but never in preference to a row that names a version."""
    assert models.pick_highest_model(["Opus", "Sonnet 4.6"], "opus")["version"] is None
    both = models.pick_highest_model(["Opus", "Opus 4.8"], "opus")
    assert both["version"] == 4.8, "a named version outranks a bare family row"


def test_pick_highest_below_steps_back_one_release():
    """The step-back path: the newest failed, so take the best row under it —
    with no hardcoded 'previous version' anywhere."""
    rows = ["Opus 6.0", "Opus 5.0", "Opus 4.8"]
    best = models.pick_highest_model(rows, "opus", below=6.0)
    assert best["version"] == 5.0


def test_pick_highest_below_never_returns_the_failed_version():
    rows = ["Opus 6.0", "Opus 6.0 (max)"]
    assert models.pick_highest_model(rows, "opus", below=6.0) is None, (
        "stepping back must not re-pick the model that just failed"
    )


def test_pick_highest_below_skips_version_less_rows():
    """An un-versioned row cannot be proven older than what just failed, so it
    is not a step-back target — picking it could re-select the failure."""
    assert models.pick_highest_model(["Opus"], "opus", below=5.0) is None


def test_a_family_word_with_a_regex_metacharacter_falls_back():
    """⛔ The family word is interpolated into four `new RegExp(...)` sites in
    research.py's page.evaluate strings, and the overlay may supply any string
    for it. One metacharacter would throw inside the browser and take model
    selection down on every run. Rejecting the value here removes the class at
    the source, which beats escaping correctly at four call sites forever."""
    import json as _json
    for bad in ("op(us", "opus)", "op[us", "opus|sonnet", "opus.*", "opus\\\\"):
        p = _MP_TMP / "model_refresh.json"
        p.write_text(_json.dumps({"claude": {"labels": {"family": bad}}}), encoding="utf-8")
        old = models._MODEL_REFRESH_OVERLAY_PATH
        try:
            models._MODEL_REFRESH_OVERLAY_PATH = p
            assert models.p2_family("claude") == "opus", (
                f"a family word containing a metacharacter must not reach the JS: {bad!r}"
            )
        finally:
            models._MODEL_REFRESH_OVERLAY_PATH = old


def test_a_plain_family_rename_is_still_honoured():
    """The validation must reject metacharacters WITHOUT blocking the thing the
    overlay exists for — renaming the family."""
    import json as _json
    p = _MP_TMP / "model_refresh.json"
    p.write_text(_json.dumps({"claude": {"labels": {"family": "opus max"}}}), encoding="utf-8")
    old = models._MODEL_REFRESH_OVERLAY_PATH
    try:
        models._MODEL_REFRESH_OVERLAY_PATH = p
        assert models.p2_family("claude") == "opus max"
    finally:
        models._MODEL_REFRESH_OVERLAY_PATH = old
