"""Unit tests for Track D `auth/pairing.py`.

Covers the deterministic surface — code generation, normalization,
display formatting. The HTTP exchange against signInWithCustomToken is
network-dependent; integration-test it elsewhere.
"""

from __future__ import annotations

import re

import pytest

from auth import pairing


class TestGenerateCode:
    def test_returns_8_chars(self):
        code = pairing.generate_code()
        assert len(code) == pairing.CODE_LENGTH == 8

    def test_uses_only_alphabet_chars(self):
        # Generate a bunch of codes; every char in every code must be in
        # ALPHABET. Stronger than a single sample.
        for _ in range(200):
            code = pairing.generate_code()
            for ch in code:
                assert ch in pairing.ALPHABET, (
                    f"char {ch!r} not in ALPHABET — got code {code!r}"
                )

    def test_alphabet_excludes_ambiguous_chars(self):
        # 0, 1, I, L, O must never appear. The whole point of the 31-char
        # set is human-typeability.
        for forbidden in "01ILO":
            assert forbidden not in pairing.ALPHABET

    def test_alphabet_size_31(self):
        assert len(pairing.ALPHABET) == 31

    def test_alphabet_size_matches_docstring(self):
        # digits 2-9 = 8 chars; uppercase A-Z minus I/L/O = 26 - 3 = 23
        assert len(pairing.ALPHABET) == 8 + 23

    def test_codes_have_high_entropy(self):
        # No two consecutive generations should be identical at our scale
        # (31^8 ≈ 8e11 search space). Generate a few hundred and assert
        # they're all distinct.
        codes = {pairing.generate_code() for _ in range(500)}
        assert len(codes) == 500


class TestNormalizeCode:
    def test_uppercase_input_passes_through(self):
        assert pairing.normalize_code("K7XQ9B2M") == "K7XQ9B2M"

    def test_lowercase_gets_uppercased(self):
        assert pairing.normalize_code("k7xq9b2m") == "K7XQ9B2M"

    def test_mixed_case_normalizes(self):
        assert pairing.normalize_code("K7xQ9b2M") == "K7XQ9B2M"

    def test_dash_separator_stripped(self):
        assert pairing.normalize_code("K7XQ-9B2M") == "K7XQ9B2M"

    def test_whitespace_stripped(self):
        assert pairing.normalize_code(" K7XQ 9B2M ") == "K7XQ9B2M"

    def test_dash_and_whitespace_combined(self):
        assert pairing.normalize_code("  k7xq - 9b2m  ") == "K7XQ9B2M"

    def test_empty_string_returns_none(self):
        assert pairing.normalize_code("") is None

    def test_none_input_returns_none(self):
        # Real callers won't pass None, but the type annotation says str —
        # tolerate falsey inputs gracefully.
        assert pairing.normalize_code(None) is None  # type: ignore[arg-type]

    def test_too_short_returns_none(self):
        assert pairing.normalize_code("K7XQ9B2") is None

    def test_too_long_returns_none(self):
        assert pairing.normalize_code("K7XQ9B2MX") is None

    def test_contains_ambiguous_char_returns_none(self):
        # I, L, O, 0, 1 are not in ALPHABET. The normalize step rejects
        # them so the FE form gives the user immediate feedback.
        for forbidden in "ILOilo01":
            code = "K7XQ9B2M".replace("K", forbidden)
            assert pairing.normalize_code(code) is None, (
                f"normalize accepted forbidden char {forbidden!r}"
            )

    def test_strips_arbitrary_non_alphanumeric(self):
        # Lenient by design: anything that isn't [A-Z0-9] gets stripped,
        # not just dashes/whitespace. This matches the FE `normalizeCode`
        # in `lib/pair-code.ts` so paste-from-terminal works even if the
        # user picks up an extra character. The 8-char length check + the
        # alphabet whitelist after stripping still reject malformed input.
        assert pairing.normalize_code("K7XQ#9B2M") == "K7XQ9B2M"
        assert pairing.normalize_code("K7XQ_9B2M") == "K7XQ9B2M"
        assert pairing.normalize_code("K7XQ@9B2M") == "K7XQ9B2M"

    def test_strip_then_too_short_returns_none(self):
        # After stripping special chars, the remaining length must be 8.
        # 7 alphanumeric + 1 special → 7 chars → reject.
        assert pairing.normalize_code("K7X@9B2M") is None


class TestFormatForDisplay:
    def test_inserts_dash_at_position_4(self):
        assert pairing.format_for_display("K7XQ9B2M") == "K7XQ-9B2M"

    def test_wrong_length_passes_through(self):
        # Defensive: never error on unexpected input, just return as-is.
        assert pairing.format_for_display("K7XQ") == "K7XQ"
        assert pairing.format_for_display("") == ""

    def test_roundtrip_with_normalize(self):
        # The fundamental contract: a code that's been display-formatted
        # must still normalize back to itself.
        code = pairing.generate_code()
        displayed = pairing.format_for_display(code)
        assert pairing.normalize_code(displayed) == code


class TestExchangeCustomTokenErrors:
    """We don't hit the real endpoint here — just the error-shape contract.

    Network-dependent behavior is covered by integration tests once the
    pair flow runs end-to-end in D5.
    """

    def test_exchange_raises_on_http_error(self, monkeypatch):
        class FakeResponse:
            ok = False
            status_code = 401
            text = "INVALID_CUSTOM_TOKEN"

        def fake_post(*args, **kwargs):
            return FakeResponse()

        monkeypatch.setattr(pairing.requests, "post", fake_post)
        with pytest.raises(pairing.CustomTokenExchangeError) as exc:
            pairing.exchange_custom_token("fake-token", "fake-key")
        assert "401" in str(exc.value)

    def test_exchange_returns_dict_on_success(self, monkeypatch):
        class FakeResponse:
            ok = True

            def json(self):
                return {
                    "idToken": "id-tok",
                    "refreshToken": "refresh-tok",
                    "expiresIn": "3600",
                    "localId": "device-xyz",
                }

        def fake_post(*args, **kwargs):
            return FakeResponse()

        monkeypatch.setattr(pairing.requests, "post", fake_post)
        result = pairing.exchange_custom_token("fake-token", "fake-key")
        assert result["localId"] == "device-xyz"
        assert result["refreshToken"] == "refresh-tok"


# ─── Cross-check against the FE alphabet ──────────────────────────────
# The FE has its own ALPHABET constant in `lib/pair-code.ts`. The two
# MUST stay byte-identical, otherwise codes generated by BE will fail
# FE validation (or vice versa).
def test_be_alphabet_matches_fe_string():
    # Hardcoded copy from `lib/pair-code.ts:11`. If this assertion fires
    # because someone updated one side, update both.
    fe_alphabet = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
    assert pairing.ALPHABET == fe_alphabet


def test_alphabet_is_in_canonical_order():
    # Lock the exact ordering — accidental shuffling could change the
    # modulo bias profile if anyone touches generation in the future.
    # (Currently `secrets.choice` doesn't care about order, but a future
    # rejection-sampling refactor might assume monotonic indexing.)
    assert pairing.ALPHABET == "".join(sorted(pairing.ALPHABET))
    # Quick sanity — first/last anchors.
    assert pairing.ALPHABET[0] == "2"
    assert pairing.ALPHABET[-1] == "Z"


def test_alphabet_no_duplicate_chars():
    assert len(set(pairing.ALPHABET)) == len(pairing.ALPHABET)
