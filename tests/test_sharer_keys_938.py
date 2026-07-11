"""#938 — sharer keys: a sharer's own API keys are used ONLY for runs THEY
submit on a shared research computer.

A sharer saves keys in THEIR OWN users/{sharerUid}/settings/prefs at
apiKeys.byDevice.{deviceId}.{anthropic,gemini} (the settings/prefs read rule
already allows the synth device user via deviceMemberOf — the sharer is in
this device's sharedWith[]; the owner can never read them). At run start,
run_pipeline binds the submitter uid BEFORE any key resolution; when the
submitter isn't the device owner, _read_firestore_api_keys overlays the
submitter's explicit per-device keys over the owner chain. Resolution per
field: sharer byDevice > owner byDevice > owner flat > user-scope env >
os.environ. Sharer FLAT keys are deliberately ignored on someone else's
computer, and the overlay is allowlisted to {anthropic, gemini}.

The submitter context is entry-only + change-triggered — NOT cleared in
run_pipeline's finally — because the auto-retry recursion forwards the
resolved key as cli_key (never re-reading Firestore) and the post-run
title/summary daemon threads resolve keys after the run returns; both must
keep the run's attribution.
"""
import inspect

import research

MODSRC = inspect.getsource(research)


# ── _overlay_submitter_keys: pure merge semantics ─────────────────────────────

def test_sharer_bydevice_outranks_owner_chain_per_field():
    merged = {"anthropic": "sk-ant-owner", "gemini": "AIza-owner"}
    sharer = {"byDevice": {"pc-abc123": {"anthropic": "sk-ant-sharer"}}}
    out, fields = research._overlay_submitter_keys(merged, sharer, "pc-abc123")
    assert out["anthropic"] == "sk-ant-sharer", "sharer's per-device key must win"
    assert out["gemini"] == "AIza-owner", "fields the sharer didn't bring keep the owner chain"
    assert fields == ["anthropic"]


def test_sharer_flat_keys_are_ignored_on_someone_elses_computer():
    # Per-device is the explicit opt-in — a sharer's account-wide flat key
    # must never silently bill their account for runs on a shared computer.
    merged = {"anthropic": "sk-ant-owner"}
    sharer = {"anthropic": "sk-ant-sharer-flat", "gemini": "AIza-sharer-flat"}
    out, fields = research._overlay_submitter_keys(merged, sharer, "pc-abc123")
    assert out == {"anthropic": "sk-ant-owner"}
    assert fields == []


def test_sharer_other_device_entry_never_applies():
    merged = {"anthropic": "sk-ant-owner"}
    sharer = {"byDevice": {"other-device": {"anthropic": "sk-ant-sharer"}}}
    out, fields = research._overlay_submitter_keys(merged, sharer, "pc-abc123")
    assert out == {"anthropic": "sk-ant-owner"}
    assert fields == []


def test_overlay_is_allowlisted_to_anthropic_and_gemini():
    # A stray byDevice field (e.g. deepgram) must never shadow the owner's
    # value — the sharer overlay only carries the two user-facing keys.
    merged = {"deepgram": "dg-owner"}
    sharer = {"byDevice": {"pc": {"deepgram": "dg-sharer", "gemini": "AIza-s"}}}
    out, fields = research._overlay_submitter_keys(merged, sharer, "pc")
    assert out["deepgram"] == "dg-owner"
    assert out["gemini"] == "AIza-s"
    assert fields == ["gemini"]
    assert research._SHARER_OVERRIDABLE_FIELDS == ("anthropic", "gemini")


def test_empty_sharer_value_never_shadows_owner():
    merged = {"anthropic": "sk-ant-owner"}
    sharer = {"byDevice": {"pc": {"anthropic": "   "}}}
    out, fields = research._overlay_submitter_keys(merged, sharer, "pc")
    assert out["anthropic"] == "sk-ant-owner"
    assert fields == []


def test_overlay_malformed_shapes_are_safe():
    # The sharer's prefs doc is client-writable — never trust the shape.
    merged = {"anthropic": "sk-ant-owner"}
    assert research._overlay_submitter_keys(merged, None, "pc") == (merged, [])
    assert research._overlay_submitter_keys(merged, {"byDevice": "nope"}, "pc") == (merged, [])
    assert research._overlay_submitter_keys(merged, {"byDevice": {"pc": "nope"}}, "pc") == (merged, [])
    assert research._overlay_submitter_keys(merged, {"byDevice": {"pc": {"anthropic": 123}}}, "pc") == (merged, [])
    assert research._overlay_submitter_keys(None, {"byDevice": {"pc": {"gemini": "AIza-s"}}}, "pc") == ({"gemini": "AIza-s"}, ["gemini"])
    assert research._overlay_submitter_keys(merged, {}, None) == (merged, [])


def test_overlay_strips_values_and_sorts_fields():
    out, fields = research._overlay_submitter_keys(
        {}, {"byDevice": {"pc": {"gemini": " AIza-s ", "anthropic": " sk-a "}}}, "pc")
    assert out == {"gemini": "AIza-s", "anthropic": "sk-a"}
    assert fields == ["anthropic", "gemini"], "sorted — stable log/attribution output"


def test_overlay_does_not_mutate_the_input_merged_dict():
    merged = {"anthropic": "sk-ant-owner"}
    research._overlay_submitter_keys(
        merged, {"byDevice": {"pc": {"anthropic": "sk-ant-sharer"}}}, "pc")
    assert merged == {"anthropic": "sk-ant-owner"}


# ── wiring: the sharer overlay sits on the same single choke point ───────────

def test_reader_overlays_submitter_keys_only_when_submitter_differs():
    src = inspect.getsource(research._read_firestore_api_keys)
    assert "_overlay_submitter_keys(" in src
    assert "submitter != uid" in src, "owner-submitted runs must be byte-identical to pre-#938"


def test_reader_sharer_block_fails_open_to_owner_chain():
    # A mid-run unshare 403s the sharer prefs read — that must degrade to
    # the owner chain, NOT bubble to the reader's outer except (which
    # returns {} and would nuke the owner keys too).
    src = inspect.getsource(research._read_firestore_api_keys)
    sharer_block = src.split("_overlay_submitter_keys(")[0]
    assert sharer_block.count("try:") >= 2, "sharer read needs its own inner try"
    assert "except Exception" in src.split("_overlay_submitter_keys(")[1]
    helper = inspect.getsource(research._read_submitter_prefs_keys)
    assert "except Exception" in helper, "prefs read itself is fail-open"


def test_submitter_prefs_read_is_cached():
    # resolve_gemini_api_key has no cache (narrator re-resolves every ~6s
    # tick) — the 30s single-slot memo keeps sharer runs from doubling the
    # per-resolve Firestore reads.
    helper = inspect.getsource(research._read_submitter_prefs_keys)
    assert "_SHARER_PREFS_CACHE" in helper
    assert research._SHARER_PREFS_TTL == 30.0


# ── submitter context: entry-only, change-triggered ──────────────────────────

def test_run_pipeline_binds_submitter_before_key_resolution():
    src = inspect.getsource(research.run_pipeline)
    bind = src.index("_set_run_submitter(uid)")
    resolve = src.index("resolve_api_key(api_key)")
    assert bind < resolve, "the Anthropic key is baked into cua_client at resolve time"


def test_run_pipeline_finally_does_not_clear_the_submitter():
    # Entry-only by design: the auto-retry recursion forwards the resolved
    # key as cli_key (skipping Firestore — a cleared memo would mis-attribute
    # retry error cards) and post-run title/summary daemon threads resolve
    # keys after the run returns.
    src = inspect.getsource(research.run_pipeline)
    assert src.count("_set_run_submitter(") == 1, "bind once at entry; never clear in-function"


def test_set_run_submitter_change_clears_cache_and_memos():
    prev = research._RUN_SUBMITTER["uid"]
    try:
        research._set_run_submitter("uid-owner")
        research._RESOLVED_KEY_CACHE.update(key="sk-cached", ts=9e12)
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=["anthropic"], uid="uid-owner")
        research._SHARER_PREFS_CACHE.update(uid="uid-owner", keys={"x": "y"}, ts=9e12)
        research._set_run_submitter("uid-sharer")
        assert research._RUN_SUBMITTER["uid"] == "uid-sharer"
        assert research._RESOLVED_KEY_CACHE == {"key": None, "ts": 0.0}, \
            "a ≤60s cached owner key must never cross into a sharer's run"
        assert research._SHARER_KEY_OVERRIDE_MEMO == {"fields": None, "uid": None}
        assert research._SHARER_PREFS_CACHE == {"uid": None, "keys": None, "ts": 0.0}
    finally:
        research._set_run_submitter(prev)


def test_set_run_submitter_same_uid_preserves_state():
    # Same-submitter auto-retry must keep the attribution memo (the retry
    # passes the resolved key back as cli_key and never re-reads Firestore).
    prev = research._RUN_SUBMITTER["uid"]
    try:
        research._set_run_submitter("uid-sharer")
        research._RESOLVED_KEY_CACHE.update(key="sk-cached", ts=9e12)
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=["anthropic"], uid="uid-sharer")
        research._set_run_submitter("uid-sharer")
        assert research._RESOLVED_KEY_CACHE["key"] == "sk-cached"
        assert research._SHARER_KEY_OVERRIDE_MEMO["fields"] == ["anthropic"]
        research._set_run_submitter("  uid-sharer  ")
        assert research._RESOLVED_KEY_CACHE["key"] == "sk-cached", "whitespace-only change is no change"
    finally:
        research._RESOLVED_KEY_CACHE.update(key=None, ts=0.0)
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=None, uid=None)
        research._set_run_submitter(prev)


# ── error-card attribution ────────────────────────────────────────────────────

_OWNER_COPY = {
    # Byte-identical to the pre-#938 card copy — owner-submitted runs (and
    # sharer runs on the sharer's OWN key, where "your key" is accurate)
    # must not change a single character.
    "rate_limit": "Your Anthropic API key hit its rate limit. Switch to another key in Account → API Config, then Retry.",
    "cap": "Your Anthropic API key hit its usage cap. Switch to another key in Account → API Config (or raise the cap in the Anthropic console), then Retry.",
    "invalid": "Your Anthropic API key is invalid or expired. Paste a working key in Account → API Config, then Retry.",
    "probe": "The run can't start — your Anthropic API key looks rate-limited, invalid, or over its cap. Update or switch it in Account → API Config, then Retry.",
    "login_walk": "Can't verify your Claude login right now — your Anthropic API key looks rate-limited, invalid, or over its limit. Update or switch it in Account → API Config, then Retry.",
    "missing": "The run needs an Anthropic API key to start. Add it in Account → API Config, then Retry.",
}


def _with_submitter(uid, fields):
    # Simulate a run whose baked Anthropic key was attributed from `fields`:
    # set the memo AND freeze the entry snapshot the card copy reads.
    research._RUN_SUBMITTER["uid"] = uid
    research._SHARER_KEY_OVERRIDE_MEMO.update(fields=fields, uid=uid)
    research._RUN_ANTHROPIC_ATTR.update(
        is_sharers=bool(uid) and "anthropic" in (fields or []),
        captured=True,
    )


def test_card_copy_owner_run_is_byte_identical_to_pre_938(monkeypatch):
    prev = research._RUN_SUBMITTER["uid"]
    try:
        monkeypatch.setattr(research, "load_paired_uid", lambda: "uid-owner")
        _with_submitter("uid-owner", [])
        for kind, expected in _OWNER_COPY.items():
            got = research._anthropic_key_card_copy(kind, label="Claude")
            assert got == expected, f"{kind}: owner-run copy drifted"
    finally:
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=None, uid=None)
        research._set_run_submitter(prev)


def test_card_copy_sharer_run_on_own_key_keeps_your_key_copy(monkeypatch):
    prev = research._RUN_SUBMITTER["uid"]
    try:
        monkeypatch.setattr(research, "load_paired_uid", lambda: "uid-owner")
        _with_submitter("uid-sharer", ["anthropic", "gemini"])
        assert research._anthropic_key_card_copy("rate_limit") == _OWNER_COPY["rate_limit"], \
            "'Your Anthropic API key' is accurate when the sharer's own key is in play"
    finally:
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=None, uid=None)
        research._set_run_submitter(prev)


def test_card_copy_sharer_run_on_owner_key_attributes_the_owner(monkeypatch):
    prev = research._RUN_SUBMITTER["uid"]
    try:
        monkeypatch.setattr(research, "load_paired_uid", lambda: "uid-owner")
        # Sharer brought only a gemini key — the ANTHROPIC key is the owner's.
        _with_submitter("uid-sharer", ["gemini"])
        for kind in ("rate_limit", "cap", "invalid", "probe", "login_walk"):
            got = research._anthropic_key_card_copy(kind, label="Claude")
            assert "computer owner's Anthropic API key" in got, kind
            assert "add your own key" in got, f"{kind}: must point the sharer at their own fix"
            assert not got.startswith("Your Anthropic"), kind
        missing = research._anthropic_key_card_copy("missing")
        assert "Add your own for this computer" in missing
        assert "ask the owner" in missing
    finally:
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=None, uid=None)
        research._set_run_submitter(prev)


def test_card_copy_reads_frozen_snapshot_not_the_live_memo(monkeypatch):
    # The BAKED Anthropic key's attribution is frozen at run entry; the memo
    # is refreshed by narrator Gemini resolves. A mid-run prefs edit that
    # flips the memo must NOT flip an Anthropic error card (the failing key
    # never changed — it's the client baked at entry).
    prev = research._RUN_SUBMITTER["uid"]
    prev_attr = dict(research._RUN_ANTHROPIC_ATTR)
    try:
        monkeypatch.setattr(research, "load_paired_uid", lambda: "uid-owner")
        # Fresh sharer run resets the snapshot, then entry-resolve baked the
        # OWNER's anthropic key (sharer brought only gemini).
        research._set_run_submitter("uid-sharer")
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=["gemini"], uid="uid-sharer")
        research._capture_anthropic_attribution()
        assert research._anthropic_key_is_sharers() is False
        assert "computer owner's Anthropic API key" in research._anthropic_key_card_copy("rate_limit")
        # Mid-run the sharer pastes their own anthropic key — the LIVE memo
        # flips, but the baked client (and thus the card) must not.
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=["anthropic", "gemini"], uid="uid-sharer")
        assert research._anthropic_key_is_sharers() is False, "frozen snapshot must ignore memo drift"
        assert "computer owner's Anthropic API key" in research._anthropic_key_card_copy("rate_limit")
    finally:
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=None, uid=None)
        research._RUN_ANTHROPIC_ATTR.update(prev_attr)
        research._set_run_submitter(prev)


def test_capture_is_idempotent_within_a_run_but_resets_on_submitter_change():
    prev = research._RUN_SUBMITTER["uid"]
    prev_attr = dict(research._RUN_ANTHROPIC_ATTR)
    try:
        research._set_run_submitter("uid-sharer")
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=["anthropic"], uid="uid-sharer")
        research._capture_anthropic_attribution()
        assert research._RUN_ANTHROPIC_ATTR == {"is_sharers": True, "captured": True}
        # Same-submitter auto-retry: capture is a no-op (retry forwards the
        # resolved key as cli_key, so the original attribution stands even if
        # the memo drifted).
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=[], uid="uid-sharer")
        research._capture_anthropic_attribution()
        assert research._RUN_ANTHROPIC_ATTR["is_sharers"] is True, "idempotent within the run"
        # A new submitter demands a fresh capture.
        research._set_run_submitter("uid-owner")
        assert research._RUN_ANTHROPIC_ATTR == {"is_sharers": False, "captured": False}
    finally:
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=None, uid=None)
        research._RUN_ANTHROPIC_ATTR.update(prev_attr)
        research._set_run_submitter(prev)


def test_run_pipeline_captures_attribution_after_baking_the_client():
    src = inspect.getsource(research.run_pipeline)
    bake = src.index("cua_client = anthropic.Anthropic(")
    capture = src.index("_capture_anthropic_attribution()")
    assert bake < capture, "freeze attribution only after the key is baked into cua_client"


def test_card_copy_login_walk_interpolates_the_label(monkeypatch):
    prev = research._RUN_SUBMITTER["uid"]
    try:
        monkeypatch.setattr(research, "load_paired_uid", lambda: "uid-owner")
        _with_submitter("uid-sharer", [])
        assert "Gemini login" in research._anthropic_key_card_copy("login_walk", label="Gemini")
        _with_submitter("uid-owner", [])
        assert "Gemini login" in research._anthropic_key_card_copy("login_walk", label="Gemini")
    finally:
        research._SHARER_KEY_OVERRIDE_MEMO.update(fields=None, uid=None)
        research._set_run_submitter(prev)


def test_all_six_card_sites_route_through_the_attribution_helper():
    # The literal owner-copy strings must be gone from the emit sites —
    # exactly one copy of each lives inside _anthropic_key_card_copy.
    helper_src = inspect.getsource(research._anthropic_key_card_copy)
    for needle, count in (
        ('_anthropic_key_card_copy("rate_limit")', 1),
        ('_anthropic_key_card_copy("cap")', 1),
        ('_anthropic_key_card_copy("invalid")', 1),
        ('_anthropic_key_card_copy("probe")', 1),
        ('_anthropic_key_card_copy("login_walk", label=label)', 1),
        ('_anthropic_key_card_copy("missing")', 1),
    ):
        assert MODSRC.count(needle) == count, needle
    # The phase-0 missing-key trio shares one resolved message.
    assert MODSRC.count("message=_missing_msg") == 1
    assert MODSRC.count('"message": _missing_msg') == 1
    # No stray duplicates of the owner copy outside the helper.
    for phrase in ("hit its rate limit. Switch to",
                   "hit its usage cap. Switch to",
                   "invalid or expired. Paste a working key"):
        assert MODSRC.count(phrase) == helper_src.count(phrase), phrase


# ── observability: field names only, never values ─────────────────────────────

def test_sharer_override_log_names_fields_never_values():
    src = inspect.getsource(research._read_firestore_api_keys)
    assert "sharer key override active for" in src
    assert "join(s_fields)" in src
    assert "sharer key override cleared" in src
    # Change-only memo — the 6s narrator cadence must not spam the log.
    assert "_SHARER_KEY_OVERRIDE_MEMO" in src


def test_928_device_overlay_untouched():
    # #938 layers ON TOP of the #928 owner-device overlay — the base merge
    # is a frozen contract.
    src = inspect.getsource(research._overlay_device_keys)
    assert "byDevice" in src
    reader = inspect.getsource(research._read_firestore_api_keys)
    assert reader.index("_overlay_device_keys(") < reader.index("_overlay_submitter_keys("), \
        "owner chain resolves first; the sharer overlay applies on top"
