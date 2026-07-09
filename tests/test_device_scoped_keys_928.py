"""#928 — device-scoped API keys (Anthropic = CUA+Vision, Gemini = narration).

The FE Account page writes per-device overrides at
users/{owner}/settings/prefs.apiKeys.byDevice.{deviceId}.{anthropic,gemini}
(settings/prefs is owner-write-only + BE-readable via deviceMemberOf — the
sharer-safe store; the device DOC is sharer-readable so keys must never land
there). The BE overlays THIS device's entry over the flat account-wide keys
inside _read_firestore_api_keys(), the single choke point both resolvers
(resolve_api_key → CUA+Vision, resolve_gemini_api_key → narrator/polish)
route through — so a device key hot-applies within the existing 60s/5s TTL
without a restart, and clearing it on the FE cleanly reverts this device to
flat → local-env baseline.
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
