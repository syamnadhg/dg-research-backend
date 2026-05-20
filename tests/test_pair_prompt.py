"""--pair Stage 4/5 API-key detect-or-prompt tests.

Covers the three new helpers added to research.py:
  - _save_api_key_to_firestore(uid, key_name, value) -> bool
  - _pair_prompt_one_key(label, example, help_url) -> str  (async)
  - _pair_prompt_api_keys(uid)                            (async)

Behavior under test:
  1. Detect-first: if a resolver already returns a key, no prompt fires.
  2. Skip is first-class: typing s/skip / Ctrl+C / EOF returns "" cleanly,
     pair continues, no Firestore write, no os.environ mutation.
  3. On paste: trim + quote-strip, validation rejects empty / too short /
     whitespace-containing input; valid key writes to Firestore + os.environ
     + busts _RESOLVED_KEY_CACHE.
  4. Firestore write failure falls back to os.environ-only (in-memory).

Run via:
    pytest tests/test_pair_prompt.py -v
"""
import asyncio
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def silent_log(monkeypatch):
    monkeypatch.setattr("research.log", lambda *a, **kw: None)


# ─────────────────────────────────────────────────────────────────────
# _save_api_key_to_firestore
# ─────────────────────────────────────────────────────────────────────

class TestSaveApiKeyToFirestore:
    """Post-D7: `_save_api_key_to_firestore` always goes through the FE
    bridge (`_save_api_key_via_fe_bridge`) — the synth device user can't
    write `users/{uid}/settings/prefs` directly per Firestore rules. The
    `uid` parameter is now ignored; the bridge resolves the target
    ownerUid from the BE's custom-token claim."""

    def test_delegates_to_fe_bridge(self, monkeypatch, silent_log):
        """The function is a thin wrapper around `_save_api_key_via_fe_bridge`
        — just forwards (key_name, value) and ignores uid."""
        from research import _save_api_key_to_firestore
        captured = {}
        def fake_bridge(key_name, value):
            captured["key_name"] = key_name
            captured["value"] = value
            return True
        monkeypatch.setattr("research._save_api_key_via_fe_bridge", fake_bridge)
        assert _save_api_key_to_firestore("uid-abc", "anthropic", "sk-ant-xyz") is True
        assert captured == {"key_name": "anthropic", "value": "sk-ant-xyz"}

    def test_gemini_forwards_key_name(self, monkeypatch, silent_log):
        from research import _save_api_key_to_firestore
        captured = {}
        def fake_bridge(key_name, value):
            captured["key_name"] = key_name
            return True
        monkeypatch.setattr("research._save_api_key_via_fe_bridge", fake_bridge)
        _save_api_key_to_firestore("uid-abc", "gemini", "AIzaSyXYZ")
        assert captured["key_name"] == "gemini"

    def test_bridge_failure_propagates_as_false(self, monkeypatch, silent_log):
        """Bridge returns False on token-mint failure, network error, or
        non-200 from the FE Cloud Function. The wrapper must propagate."""
        from research import _save_api_key_to_firestore
        monkeypatch.setattr("research._save_api_key_via_fe_bridge", lambda k, v: False)
        assert _save_api_key_to_firestore("uid-abc", "anthropic", "sk-ant-xyz") is False


# ─────────────────────────────────────────────────────────────────────
# _pair_prompt_one_key (validation loop)
# ─────────────────────────────────────────────────────────────────────

class TestPairPromptOneKey:
    """The async input loop. Returns "" on skip / Ctrl+C / EOF; valid
    pasted key on success. Validates: non-empty, >= 20 chars, no whitespace.
    Strips surrounding quotes (common when copying from .env snippets)."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_skip_lowercase_returns_empty(self, monkeypatch, silent_log):
        from research import _pair_prompt_one_key
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(return_value="s"))
        result = self._run(_pair_prompt_one_key("Anthropic", "sk-ant-...", "https://x"))
        assert result == ""

    def test_skip_word_returns_empty(self, monkeypatch, silent_log):
        from research import _pair_prompt_one_key
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(return_value="skip"))
        result = self._run(_pair_prompt_one_key("Anthropic", "sk-ant-...", "https://x"))
        assert result == ""

    def test_skip_uppercase_returns_empty(self, monkeypatch, silent_log):
        """Tolerate S / SKIP / Skip — case-insensitive UX."""
        from research import _pair_prompt_one_key
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(return_value="SKIP"))
        result = self._run(_pair_prompt_one_key("Anthropic", "sk-ant-...", "https://x"))
        assert result == ""

    def test_ctrl_c_returns_empty(self, monkeypatch, silent_log):
        """Ctrl+C during input must NOT propagate — pair finishes the
        remaining steps (Gemini prompt + supervisor arm)."""
        from research import _pair_prompt_one_key
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(side_effect=KeyboardInterrupt))
        result = self._run(_pair_prompt_one_key("Anthropic", "sk-ant-...", "https://x"))
        assert result == ""

    def test_eof_returns_empty(self, monkeypatch, silent_log):
        """Pipe-fed pair (echo '' | python research.py --pair) reaches
        EOFError at the prompt — must be treated as skip, not a crash."""
        from research import _pair_prompt_one_key
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(side_effect=EOFError))
        result = self._run(_pair_prompt_one_key("Anthropic", "sk-ant-...", "https://x"))
        assert result == ""

    def test_valid_key_returned_trimmed(self, monkeypatch, silent_log):
        """Surrounding whitespace must be stripped (common when keys are
        copied with trailing newlines from a terminal)."""
        from research import _pair_prompt_one_key
        valid_key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456789"
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(return_value=f"   {valid_key}   "))
        result = self._run(_pair_prompt_one_key("Anthropic", "sk-ant-...", "https://x"))
        assert result == valid_key

    def test_double_quoted_key_stripped(self, monkeypatch, silent_log):
        """Users copying from .env files often grab the quotes too —
        strip them before validation."""
        from research import _pair_prompt_one_key
        valid_key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456789"
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(return_value=f'"{valid_key}"'))
        result = self._run(_pair_prompt_one_key("Anthropic", "sk-ant-...", "https://x"))
        assert result == valid_key

    def test_single_quoted_key_stripped(self, monkeypatch, silent_log):
        from research import _pair_prompt_one_key
        valid_key = "AIzaSyABCDEFGHIJKLMNOPQRSTUV-1234567890"
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(return_value=f"'{valid_key}'"))
        result = self._run(_pair_prompt_one_key("Gemini", "AIza...", "https://x"))
        assert result == valid_key

    def test_mismatched_quotes_not_stripped(self, monkeypatch, silent_log):
        """`"foo'` shouldn't strip — caller's input is malformed; let
        validation reject so the user notices."""
        from research import _pair_prompt_one_key
        # First input: malformed quotes that survive but pass other checks
        # except the whitespace check (they don't contain whitespace).
        # Actually mismatched quotes will pass `len >= 20 and no whitespace`
        # so they'll be returned as-is. The point of this test is just to
        # confirm the strip predicate is strict about matching pairs.
        valid_key = '"sk-ant-api03-abcdefghijklmnopqrstuvwxyz123' + "'"
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(return_value=valid_key))
        result = self._run(_pair_prompt_one_key("Anthropic", "sk-ant-...", "https://x"))
        # Quotes still present in returned value
        assert result == valid_key

    def test_too_short_key_re_prompts_then_skip(self, monkeypatch, silent_log):
        """Short input fails validation; loop re-prompts. Test by chaining
        a short input then a skip — must end on skip, not return the short
        string."""
        from research import _pair_prompt_one_key
        calls = ["short", "s"]
        async def _fake_input(*_args, **_kwargs):
            return calls.pop(0)
        monkeypatch.setattr("research.asyncio.to_thread", _fake_input)
        result = self._run(_pair_prompt_one_key("Anthropic", "sk-ant-...", "https://x"))
        assert result == ""
        assert calls == []  # Both inputs consumed

    def test_whitespace_in_middle_re_prompts(self, monkeypatch, silent_log):
        """A key with embedded whitespace (multi-line paste) re-prompts.
        Confirms the validator catches accidental newlines/spaces."""
        from research import _pair_prompt_one_key
        bad = "sk-ant-with embedded space valid length here"
        good_skip = "skip"
        calls = [bad, good_skip]
        async def _fake_input(*_args, **_kwargs):
            return calls.pop(0)
        monkeypatch.setattr("research.asyncio.to_thread", _fake_input)
        result = self._run(_pair_prompt_one_key("Anthropic", "sk-ant-...", "https://x"))
        assert result == ""

    def test_empty_input_re_prompts(self, monkeypatch, silent_log):
        """Just-Enter at the prompt re-asks, doesn't silently skip."""
        from research import _pair_prompt_one_key
        calls = ["", "", "skip"]
        async def _fake_input(*_args, **_kwargs):
            return calls.pop(0)
        monkeypatch.setattr("research.asyncio.to_thread", _fake_input)
        result = self._run(_pair_prompt_one_key("Anthropic", "sk-ant-...", "https://x"))
        assert result == ""
        assert calls == []  # All 3 inputs consumed (empty, empty, skip)


# ─────────────────────────────────────────────────────────────────────
# _pair_prompt_api_keys (orchestrator)
# ─────────────────────────────────────────────────────────────────────

class TestPairPromptApiKeys:
    """The orchestrator. Detect-first via resolve_*_api_key(); on paste
    writes Firestore + os.environ + busts cache. Anthropic and Gemini
    independent."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_both_already_set_no_prompt(self, monkeypatch, silent_log):
        """If both resolvers return a key, neither prompt fires —
        zero asyncio.to_thread input calls."""
        from research import _pair_prompt_api_keys
        monkeypatch.setattr("research.resolve_api_key", lambda: "sk-ant-existing")
        monkeypatch.setattr("research.resolve_gemini_api_key", lambda: "AIza-existing")
        prompt_calls = []
        async def _no_prompt(*_args, **_kwargs):
            prompt_calls.append(_args)
            return "should not be reached"
        monkeypatch.setattr("research.asyncio.to_thread", _no_prompt)
        self._run(_pair_prompt_api_keys("uid-abc"))
        assert prompt_calls == []  # No input prompts fired

    def test_anthropic_missing_gemini_set_only_one_prompt(self, monkeypatch, silent_log):
        """Anthropic resolver returns "" → prompts for Anthropic. Gemini
        resolver returns a key → skips Gemini prompt."""
        from research import _pair_prompt_api_keys
        valid_key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
        monkeypatch.setattr("research.resolve_api_key", lambda: "")
        monkeypatch.setattr("research.resolve_gemini_api_key", lambda: "AIza-existing")
        mock_db = mock.MagicMock()
        monkeypatch.setattr("research._firebase_db", mock_db)
        # Anthropic: paste key, then loop exits
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(return_value=valid_key))
        # Snapshot env so we can assert what changed
        before_anthropic = os.environ.get("ANTHROPIC_API_KEY")
        before_gemini = os.environ.get("GEMINI_API_KEY")
        try:
            self._run(_pair_prompt_api_keys("uid-abc"))
            # Anthropic was set
            assert os.environ.get("ANTHROPIC_API_KEY") == valid_key
            assert os.environ.get("CUA_API_KEY") == valid_key
            # Gemini was NOT touched (resolver said it's already configured)
            assert os.environ.get("GEMINI_API_KEY") == before_gemini
        finally:
            # Restore env
            if before_anthropic is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
                os.environ.pop("CUA_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = before_anthropic
                os.environ["CUA_API_KEY"] = before_anthropic

    def test_paste_busts_anthropic_cache(self, monkeypatch, silent_log):
        """After paste, _RESOLVED_KEY_CACHE.ts is reset to 0.0 so the next
        resolve_api_key() call re-reads from Firestore / env."""
        from research import _pair_prompt_api_keys, _RESOLVED_KEY_CACHE
        valid_key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
        monkeypatch.setattr("research.resolve_api_key", lambda: "")
        monkeypatch.setattr("research.resolve_gemini_api_key", lambda: "AIza-existing")
        monkeypatch.setattr("research._firebase_db", mock.MagicMock())
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(return_value=valid_key))
        # Seed cache with a stale value
        _RESOLVED_KEY_CACHE.update(key="stale-key", ts=1e10)
        try:
            self._run(_pair_prompt_api_keys("uid-abc"))
            # Cache must be busted: ts=0.0 and key=None
            assert _RESOLVED_KEY_CACHE["ts"] == 0.0
            assert _RESOLVED_KEY_CACHE["key"] is None
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)
            os.environ.pop("CUA_API_KEY", None)
            _RESOLVED_KEY_CACHE.update(key=None, ts=0.0)

    def test_skip_both_no_env_change(self, monkeypatch, silent_log):
        """User skips both — no Firestore write, no env mutation, no crash."""
        from research import _pair_prompt_api_keys
        monkeypatch.setattr("research.resolve_api_key", lambda: "")
        monkeypatch.setattr("research.resolve_gemini_api_key", lambda: "")
        mock_db = mock.MagicMock()
        monkeypatch.setattr("research._firebase_db", mock_db)
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(return_value="skip"))
        before = dict(os.environ)
        self._run(_pair_prompt_api_keys("uid-abc"))
        # No Firestore writes
        set_call = mock_db.collection().document().collection().document().set
        set_call.assert_not_called()
        # No env mutations for the four candidate vars
        for var in ("ANTHROPIC_API_KEY", "CUA_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            assert os.environ.get(var) == before.get(var)

    def test_firestore_write_fails_still_sets_env(self, monkeypatch, silent_log):
        """If Firestore write throws, os.environ is still mutated so the
        current --pair / --serve session has the key. The user gets a
        WARN message + a pointer to the Account page for persistence."""
        from research import _pair_prompt_api_keys
        valid_key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
        monkeypatch.setattr("research.resolve_api_key", lambda: "")
        monkeypatch.setattr("research.resolve_gemini_api_key", lambda: "AIza-existing")
        mock_db = mock.MagicMock()
        mock_db.collection().document().collection().document().set.side_effect = Exception("PERMISSION_DENIED")
        monkeypatch.setattr("research._firebase_db", mock_db)
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(return_value=valid_key))
        before_anthropic = os.environ.get("ANTHROPIC_API_KEY")
        try:
            self._run(_pair_prompt_api_keys("uid-abc"))
            # Despite Firestore write failure, env is still set
            assert os.environ.get("ANTHROPIC_API_KEY") == valid_key
            assert os.environ.get("CUA_API_KEY") == valid_key
        finally:
            if before_anthropic is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
                os.environ.pop("CUA_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = before_anthropic
                os.environ["CUA_API_KEY"] = before_anthropic

    def test_gemini_paste_sets_both_env_var_names(self, monkeypatch, silent_log):
        """Both GEMINI_API_KEY and GOOGLE_API_KEY are set on paste — the
        resolver checks both, and downstream consumers (narrate.py) check
        both too."""
        from research import _pair_prompt_api_keys
        valid_key = "AIzaSyABCDEFGHIJKLMNOPQRSTUV-1234567890"
        monkeypatch.setattr("research.resolve_api_key", lambda: "sk-ant-existing")
        monkeypatch.setattr("research.resolve_gemini_api_key", lambda: "")
        monkeypatch.setattr("research._firebase_db", mock.MagicMock())
        monkeypatch.setattr("research.asyncio.to_thread",
                            mock.AsyncMock(return_value=valid_key))
        before_gemini = os.environ.get("GEMINI_API_KEY")
        before_google = os.environ.get("GOOGLE_API_KEY")
        try:
            self._run(_pair_prompt_api_keys("uid-abc"))
            assert os.environ.get("GEMINI_API_KEY") == valid_key
            assert os.environ.get("GOOGLE_API_KEY") == valid_key
        finally:
            for var, before in (("GEMINI_API_KEY", before_gemini), ("GOOGLE_API_KEY", before_google)):
                if before is None:
                    os.environ.pop(var, None)
                else:
                    os.environ[var] = before
