"""#928 — device-scoped API keys (Anthropic = CUA+Vision, Gemini = narration).

The FE Account page writes per-device overrides at
users/{owner}/deviceKeys/{deviceId} — one owner-write-only document per
computer, readable by the machine whose deviceId claim matches the path (the
device DOC is sharer-readable so keys must never land there). The BE overlays
THIS device's doc over the legacy byDevice map and the flat account-wide keys
inside _read_firestore_api_keys(), the single choke point both resolvers
(resolve_api_key → CUA+Vision, resolve_gemini_api_key → narrator/polish)
route through — so a device key hot-applies within the existing 60s/5s TTL
without a restart, and clearing it on the FE cleanly reverts this device to
flat → local-env baseline.

The byDevice map inside settings/prefs is the PREVIOUS home, kept read-only
for anyone who hasn't signed in since the move (the FE sweep copies it across
and deletes it). Reading one machine's key out of it needed read access to
the whole prefs doc, which on a SHARED computer meant the owner's machine
reading a sharer's account-wide keys, pair-code-lock hash and delivery
address — see test_sharer_keys_938.
"""
import inspect

import research

MODSRC = inspect.getsource(research)


# ── _overlay_device_keys: pure merge semantics ────────────────────────────────

def test_device_override_outranks_flat():
    keys = {
        "anthropic": "sk-ant-flat",
        "gemini": "AIza-flat",
        "byDevice": {"pc-abc123": {"anthropic": "sk-ant-device"}},
    }
    merged = research._overlay_device_keys(keys, "pc-abc123")
    assert merged["anthropic"] == "sk-ant-device", "this device's key must win"
    assert merged["gemini"] == "AIza-flat", "fields without an override keep the flat value"


def test_other_devices_overrides_never_apply():
    keys = {
        "anthropic": "sk-ant-flat",
        "byDevice": {"other-device": {"anthropic": "sk-ant-other"}},
    }
    merged = research._overlay_device_keys(keys, "pc-abc123")
    assert merged["anthropic"] == "sk-ant-flat"


def test_empty_device_value_never_shadows_flat():
    # Clear-on-the-FE writes deleteField, but a raced/partial write can leave
    # "" — an empty override must NOT blank this device's working flat key.
    keys = {
        "anthropic": "sk-ant-flat",
        "byDevice": {"pc-abc123": {"anthropic": "   "}},
    }
    merged = research._overlay_device_keys(keys, "pc-abc123")
    assert merged["anthropic"] == "sk-ant-flat"


def test_bydevice_container_never_leaks_into_result():
    keys = {"byDevice": {"pc-abc123": {"gemini": "AIza-dev"}}}
    merged = research._overlay_device_keys(keys, "pc-abc123")
    assert "byDevice" not in merged
    assert merged == {"gemini": "AIza-dev"}


def test_no_device_id_falls_back_to_flat_only():
    keys = {"anthropic": "sk-ant-flat", "byDevice": {"pc-abc123": {"anthropic": "x"}}}
    assert research._overlay_device_keys(keys, None) == {"anthropic": "sk-ant-flat"}


def test_malformed_shapes_are_safe():
    # Firestore data is client-writable — never trust the shape.
    assert research._overlay_device_keys(None, "pc-abc123") == {}
    assert research._overlay_device_keys({"byDevice": "not-a-dict"}, "pc") == {}
    assert research._overlay_device_keys(
        {"byDevice": {"pc": "not-a-dict"}, "gemini": "AIza-flat"}, "pc"
    ) == {"gemini": "AIza-flat"}
    # Non-string values are dropped, not str()-mangled.
    assert research._overlay_device_keys({"anthropic": 123}, "pc") == {}


def test_values_are_stripped():
    merged = research._overlay_device_keys(
        {"byDevice": {"pc": {"anthropic": "  sk-ant-x  "}}}, "pc")
    assert merged["anthropic"] == "sk-ant-x"


# ── the canonical per-device doc (layer 3) ───────────────────────────────────

def test_device_doc_outranks_flat_and_the_legacy_map():
    # The FE writes only the doc now, and its sign-in sweep deletes the map
    # once copied — so a value still in the map during that window is the
    # older one by construction.
    keys = {
        "anthropic": "sk-ant-flat",
        "byDevice": {"pc-abc123": {"anthropic": "sk-ant-legacy"}},
    }
    merged = research._overlay_device_keys(
        keys, "pc-abc123", {"anthropic": "sk-ant-doc"})
    assert merged["anthropic"] == "sk-ant-doc"


def test_legacy_map_still_applies_when_the_doc_has_no_such_field():
    # An install that hasn't migrated must keep working unchanged — and a
    # doc carrying only ONE field must not blank the other.
    keys = {"byDevice": {"pc": {"anthropic": "sk-ant-legacy", "gemini": "AIza-legacy"}}}
    merged = research._overlay_device_keys(keys, "pc", {"anthropic": "sk-ant-doc"})
    assert merged == {"anthropic": "sk-ant-doc", "gemini": "AIza-legacy"}


def test_device_doc_alone_needs_no_prefs_doc_at_all():
    merged = research._overlay_device_keys({}, "pc", {"gemini": "AIza-doc"})
    assert merged == {"gemini": "AIza-doc"}


def test_empty_or_malformed_doc_never_shadows_the_chain():
    keys = {"anthropic": "sk-ant-flat"}
    for doc in (None, {}, "nope", {"anthropic": "   "}, {"anthropic": 123},
                {"updatedAt": object()}):
        merged = research._overlay_device_keys(keys, "pc", doc)
        assert merged["anthropic"] == "sk-ant-flat", doc


def test_device_doc_values_are_stripped():
    merged = research._overlay_device_keys({}, "pc", {"anthropic": "  sk-d  "})
    assert merged["anthropic"] == "sk-d"


def test_reader_reads_the_device_doc_and_keeps_going_without_prefs():
    # A missing prefs doc used to end the read — with keys in their own
    # document that would drop a perfectly good key on the floor.
    src = inspect.getsource(research._read_firestore_api_keys)
    assert "_read_device_key_doc(uid, did)" in src
    assert "if not snap.exists:\n            return {}" not in src, \
        "a missing prefs doc must not short-circuit the device-key read"


def test_device_key_doc_read_is_path_scoped():
    helper = inspect.getsource(research._read_device_key_doc)
    assert 'collection("deviceKeys")' in helper
    assert "document(device_id)" in helper, "the path IS the scoping"


class _BoomDb:
    """A Firestore client that fails the moment it is touched."""

    def collection(self, *_a, **_k):
        raise RuntimeError("firestore is unreachable")


def test_device_key_doc_read_FAILS_OPEN(monkeypatch):
    # Behavioural, not a grep for `except`. A harness mutant replaced the
    # handler's body with `raise` and every source-level assertion still
    # passed — the identifier was there, the behaviour was gone. This read is
    # one document; a blip on it must degrade to the flat/local chain, not
    # take the owner's working keys down with it.
    monkeypatch.setattr(research, "_firebase_db", _BoomDb())
    assert research._read_device_key_doc("u1", "pc-abc") == {}


def test_device_key_doc_read_skips_cleanly_when_unconfigured(monkeypatch):
    monkeypatch.setattr(research, "_firebase_db", None)
    assert research._read_device_key_doc("u1", "pc-abc") == {}
    monkeypatch.setattr(research, "_firebase_db", _BoomDb())
    assert research._read_device_key_doc("", "pc-abc") == {}
    assert research._read_device_key_doc("u1", "") == {}


# ── wiring: the overlay sits on the single choke point ───────────────────────

def test_firestore_reader_applies_the_device_overlay():
    src = inspect.getsource(research._read_firestore_api_keys)
    assert "_overlay_device_keys(" in src
    assert "load_device_id()" in src, "the overlay must key on THIS device's id"


def test_both_resolvers_route_through_the_reader():
    # The overlay covers CUA+Vision (anthropic) AND narrator/polish (gemini)
    # only because both resolvers read through _read_firestore_api_keys.
    for fn in (research.resolve_api_key, research.resolve_gemini_api_key):
        assert "_read_firestore_api_keys()" in inspect.getsource(fn), fn.__name__


def test_override_log_names_fields_never_values():
    # Observability without leakage: the change-only log line prints FIELD
    # NAMES (anthropic/gemini), never key values.
    src = inspect.getsource(research._read_firestore_api_keys)
    assert "device-scoped key override" in src
    assert "_dev_fields" in src and "join(_dev_fields)" in src
    assert "merged[" not in src.split("log(")[1] if "log(" in src else True


def test_override_log_counts_BOTH_homes():
    # The line reports which fields this computer overrides. Reading only the
    # legacy map would make it fall silent the moment a key migrated, and
    # worse, print "override cleared" for a key that is working fine.
    src = inspect.getsource(research._read_firestore_api_keys)
    block = src[src.index("_dev_legacy"):src.index("_prev = ")]
    assert "_dev_legacy" in block and "device_doc" in block
    assert "for src in (_dev_legacy, device_doc)" in block
