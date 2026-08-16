"""#938 — sharer keys: a sharer's own API keys are used ONLY for runs THEY
submit on a shared research computer.

A sharer saves keys in THEIR OWN users/{sharerUid}/deviceKeys/{deviceId} —
one document per computer, holding just {anthropic?, gemini?} for that
machine. The rule lets this device read the doc named after its own deviceId
claim, in a tree it is authorized for; their settings/prefs is NOT readable
from here, and the owner can never read either. At run start, run_pipeline
binds the submitter uid BEFORE any key resolution; when the submitter isn't
the device owner, _read_firestore_api_keys overlays the submitter's explicit
per-device keys over the owner chain. Resolution per field: sharer device doc
> owner device doc > owner legacy byDevice > owner flat > user-scope env >
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

def test_sharer_device_key_outranks_owner_chain_per_field():
    merged = {"anthropic": "sk-ant-owner", "gemini": "AIza-owner"}
    sharer = {"anthropic": "sk-ant-sharer"}
    out, fields = research._overlay_submitter_keys(merged, sharer)
    assert out["anthropic"] == "sk-ant-sharer", "sharer's per-device key must win"
    assert out["gemini"] == "AIza-owner", "fields the sharer didn't bring keep the owner chain"
    assert fields == ["anthropic"]


def test_sharer_flat_keys_are_ignored_on_someone_elses_computer():
    # Per-device is the explicit opt-in — a sharer's account-wide flat key
    # must never silently bill their account for runs on a shared computer.
    # The read is what enforces it now: this machine may open exactly ONE
    # document in the sharer's tree, and the flat keys are not in it.
    reader = inspect.getsource(research._read_submitter_device_keys)
    assert 'collection("deviceKeys")' in reader
    assert 'document("prefs")' not in reader, \
        "the sharer's prefs doc must not be read from someone else's computer"
    assert 'collection("settings")' not in reader


def test_sharer_other_device_doc_is_never_even_read():
    # Scoping is the path, not a lookup: the deviceId in the read is this
    # machine's, and the rule requires it to equal the token's own claim.
    src = inspect.getsource(research._read_firestore_api_keys)
    assert "_read_submitter_device_keys(submitter, did)" in src


def test_overlay_is_allowlisted_to_anthropic_and_gemini():
    # A stray field in the sharer's key doc (e.g. deepgram) must never shadow
    # the owner's value — the sharer overlay only carries the two user-facing
    # keys.
    merged = {"deepgram": "dg-owner"}
    sharer = {"deepgram": "dg-sharer", "gemini": "AIza-s"}
    out, fields = research._overlay_submitter_keys(merged, sharer)
    assert out["deepgram"] == "dg-owner"
    assert out["gemini"] == "AIza-s"
    assert fields == ["gemini"]
    assert research._SHARER_OVERRIDABLE_FIELDS == ("anthropic", "gemini")


def test_empty_sharer_value_never_shadows_owner():
    merged = {"anthropic": "sk-ant-owner"}
    out, fields = research._overlay_submitter_keys(merged, {"anthropic": "   "})
    assert out["anthropic"] == "sk-ant-owner"
    assert fields == []


def test_overlay_malformed_shapes_are_safe():
    # The sharer's key doc is client-writable — never trust the shape.
    merged = {"anthropic": "sk-ant-owner"}
    assert research._overlay_submitter_keys(merged, None) == (merged, [])
    assert research._overlay_submitter_keys(merged, "nope") == (merged, [])
    assert research._overlay_submitter_keys(merged, {"anthropic": 123}) == (merged, [])
    # A doc carrying the OLD nested shape resolves to nothing rather than
    # smuggling a dict in as a key value.
    assert research._overlay_submitter_keys(
        merged, {"byDevice": {"pc": {"anthropic": "sk-x"}}}) == (merged, [])
    assert research._overlay_submitter_keys(
        None, {"gemini": "AIza-s"}) == ({"gemini": "AIza-s"}, ["gemini"])
    assert research._overlay_submitter_keys(merged, {}) == (merged, [])


def test_overlay_strips_values_and_sorts_fields():
    out, fields = research._overlay_submitter_keys(
        {}, {"gemini": " AIza-s ", "anthropic": " sk-a "})
    assert out == {"gemini": "AIza-s", "anthropic": "sk-a"}
    assert fields == ["anthropic", "gemini"], "sorted — stable log/attribution output"


def test_overlay_does_not_mutate_the_input_merged_dict():
    merged = {"anthropic": "sk-ant-owner"}
    research._overlay_submitter_keys(merged, {"anthropic": "sk-ant-sharer"})
    assert merged == {"anthropic": "sk-ant-owner"}


# ── wiring: the sharer overlay sits on the same single choke point ───────────

def test_reader_overlays_submitter_keys_only_when_submitter_differs():
    src = inspect.getsource(research._read_firestore_api_keys)
    assert "_overlay_submitter_keys(" in src
    assert "submitter != uid" in src, "owner-submitted runs must be byte-identical to pre-#938"


def test_reader_sharer_block_fails_open_to_owner_chain():
    # A mid-run unshare 403s the sharer key read — that must degrade to
    # the owner chain, NOT bubble to the reader's outer except (which
    # returns {} and would nuke the owner keys too).
    src = inspect.getsource(research._read_firestore_api_keys)
    sharer_block = src.split("_overlay_submitter_keys(")[0]
    assert sharer_block.count("try:") >= 2, "sharer read needs its own inner try"
    assert "except Exception" in src.split("_overlay_submitter_keys(")[1]
    helper = inspect.getsource(research._read_submitter_device_keys)
    assert "except Exception" in helper, "the key read itself is fail-open"


class _BoomDb:
    """A Firestore client that fails the moment it is touched."""

    def collection(self, *_a, **_k):
        raise RuntimeError("permission denied")


class _CountingDb:
    """Self-returning stub that counts how many reads actually happen."""

    def __init__(self, payload):
        self.reads = 0
        self.payload = payload

    def collection(self, _name):
        return self

    def document(self, _name):
        return self

    def get(self):
        self.reads += 1
        return self

    @property
    def exists(self):
        return True

    def to_dict(self):
        return dict(self.payload)


def _reset_memo():
    research._SHARER_PREFS_CACHE.update(uid=None, keys=None, ts=0.0)


def test_submitter_key_read_FAILS_OPEN(monkeypatch):
    # Behavioural, not a grep for `except`. A harness mutant replaced the
    # handler's body with `raise` and the source-level assertion still passed.
    # A mid-run unshare 403s this read; degrading to the owner chain is the
    # difference between a run that finishes on the owner's key and a run that
    # dies with no key at all.
    _reset_memo()
    monkeypatch.setattr(research, "_firebase_db", _BoomDb())
    try:
        assert research._read_submitter_device_keys("sharer-alice", "pc-abc") == {}
    finally:
        _reset_memo()


def test_submitter_key_read_is_cached(monkeypatch):
    # resolve_gemini_api_key has no cache (narrator re-resolves every ~6s
    # tick) — the 30s single-slot memo keeps sharer runs from doubling the
    # per-resolve Firestore reads. Counted, not grepped: a memo whose lookup
    # is dead still mentions the cache by name on every line it used to use.
    _reset_memo()
    db = _CountingDb({"anthropic": "sk-ant-sharer"})
    monkeypatch.setattr(research, "_firebase_db", db)
    try:
        first = research._read_submitter_device_keys("sharer-alice", "pc-abc")
        second = research._read_submitter_device_keys("sharer-alice", "pc-abc")
        assert first == second == {"anthropic": "sk-ant-sharer"}
        assert db.reads == 1, "the second resolve within the window must be served from the memo"
        # A DIFFERENT submitter is a different answer and must not be served
        # the previous one — the memo is single-slot, keyed by uid.
        other = research._read_submitter_device_keys("sharer-bob", "pc-abc")
        assert db.reads == 2
        assert other == {"anthropic": "sk-ant-sharer"}
    finally:
        _reset_memo()

    assert research._SHARER_PREFS_TTL == 30.0


def test_a_denied_read_is_memoised_too(monkeypatch):
    # A revoked sharer must not retry the denied read on every narrator tick.
    _reset_memo()
    monkeypatch.setattr(research, "_firebase_db", _BoomDb())
    try:
        assert research._read_submitter_device_keys("sharer-alice", "pc-abc") == {}
        assert research._SHARER_PREFS_CACHE["uid"] == "sharer-alice"
        assert research._SHARER_PREFS_CACHE["ts"] > 0
    finally:
        _reset_memo()


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


def test_sharer_prefs_doc_is_no_longer_read_anywhere():
    # The finding: this machine is the OWNER's hardware, and it was reading
    # the SHARER's whole prefs doc — every key they had saved for every
    # computer, their pair-code-lock hash, their delivery address — to pick
    # out the one key they had given THIS machine.
    #
    # There is exactly ONE prefs read left in the key path, and it happens
    # before the submitter is even consulted — so it can only be the paired
    # (owner) uid's.
    src = inspect.getsource(research._read_firestore_api_keys)
    assert src.count('document("prefs")') == 1
    assert src.index('document("prefs")') < src.index("submitter = ")
    assert "_read_submitter_device_keys" in src
    assert not hasattr(research, "_read_submitter_prefs_keys"), \
        "the sharer prefs reader must be gone, not merely unused"
