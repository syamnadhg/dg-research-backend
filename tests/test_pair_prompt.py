"""--pair Stage 4/5 API-key detect-or-prompt tests.

Covers the helpers added to research.py for the pair flow:
  - _save_api_key_to_firestore(uid, key_name, value) -> bool
  - _verify_anthropic_key(key) -> "ok"|"auth_failed"|"network_error"
  - _verify_gemini_key(key)    -> "ok"|"auth_failed"|"network_error"
  - _pair_prompt_one_key(label, example, help_url)          -> str (async)
  - _pair_prompt_one_key_with_verify(...verifier...)        -> str (async)
  - _pair_prompt_api_keys(uid)                              (async)

Behavior under test:
  1. Detect-first: if a resolver already returns a key, no prompt fires.
  2. Skip is first-class: typing s/skip / Ctrl+C / EOF returns "" cleanly,
     pair continues, no Firestore write, no os.environ mutation, NO
     verifier call.
  3. On paste: trim + quote-strip, validation rejects empty / too short /
     whitespace-containing input; verified key writes to Firestore +
     os.environ + busts _RESOLVED_KEY_CACHE.
  4. Verifier "auth_failed" re-prompts up to 3x then asks save-anyway;
     "network_error" saves the key with a warning.
  5. Firestore write failure falls back to os.environ-only (in-memory).

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


def _dispatching_to_thread(canned_input, verifier_status="ok"):
    """Build an `asyncio.to_thread` replacement that dispatches by the
    called function's `__name__`. Input-style calls (getpass, input)
    receive `canned_input`; verifier calls receive `verifier_status`;
    anything else is invoked through.

    The orchestrator tests use this so a single monkeypatch covers both
    the paste prompt AND the in-wrapper verifier call without the test
    needing to know how many `asyncio.to_thread` invocations happen."""
    async def _dispatch(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        # `getpass.getpass` is implemented as `win_getpass` on Windows
        # and `unix_getpass` on POSIX — match any *getpass variant.
        if "getpass" in name or name == "input":
            return canned_input
        if name.startswith("_verify_"):
            return verifier_status
        return fn(*args, **kwargs)
    return _dispatch


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
        # Anthropic: paste key, verifier says ok, loop exits
        monkeypatch.setattr("research.asyncio.to_thread",
                            _dispatching_to_thread(valid_key, "ok"))
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
                            _dispatching_to_thread(valid_key, "ok"))
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
        """User skips both — no Firestore write, no env mutation, no
        verifier call (skip is verifier-free)."""
        from research import _pair_prompt_api_keys
        monkeypatch.setattr("research.resolve_api_key", lambda: "")
        monkeypatch.setattr("research.resolve_gemini_api_key", lambda: "")
        mock_db = mock.MagicMock()
        monkeypatch.setattr("research._firebase_db", mock_db)
        # If skip="skip" is returned by the input prompt, the wrapper
        # short-circuits and never invokes the verifier. Booby-trap the
        # verifier mocks to flunk if they're called.
        def _trap(_k):
            raise AssertionError("verifier should not run on skip")
        monkeypatch.setattr("research._verify_anthropic_key", _trap)
        monkeypatch.setattr("research._verify_gemini_key", _trap)
        monkeypatch.setattr("research.asyncio.to_thread",
                            _dispatching_to_thread("skip", "ok"))
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
                            _dispatching_to_thread(valid_key, "ok"))
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
                            _dispatching_to_thread(valid_key, "ok"))
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

    def test_verifier_auth_failed_then_skip_does_not_save(self, monkeypatch, silent_log):
        """First paste fails verification, second paste is 'skip' →
        no env mutation, no Firestore write. Confirms the wrapper
        re-enters the prompt loop on auth_failed instead of saving the
        rejected key."""
        from research import _pair_prompt_api_keys
        bad_key = "sk-ant-api03-rejectednotvalidatallxxxxxxxxxxxxxxxxx"
        # First call returns bad_key (paste), second call returns "skip".
        inputs = [bad_key, "skip"]

        async def _dispatch(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if "getpass" in name or name == "input":
                return inputs.pop(0)
            if name.startswith("_verify_"):
                return "auth_failed"
            return fn(*args, **kwargs)

        monkeypatch.setattr("research.resolve_api_key", lambda: "")
        monkeypatch.setattr("research.resolve_gemini_api_key", lambda: "AIza-existing")
        monkeypatch.setattr("research._firebase_db", mock.MagicMock())
        monkeypatch.setattr("research.asyncio.to_thread", _dispatch)
        before_anthropic = os.environ.get("ANTHROPIC_API_KEY")
        try:
            self._run(_pair_prompt_api_keys("uid-abc"))
            # bad_key was never saved because skip followed auth_failed
            assert os.environ.get("ANTHROPIC_API_KEY") == before_anthropic
        finally:
            if before_anthropic is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
                os.environ.pop("CUA_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = before_anthropic
                os.environ["CUA_API_KEY"] = before_anthropic

    def test_verifier_network_error_saves_anyway(self, monkeypatch, silent_log):
        """Verifier returns 'network_error' (transient blip, offline pair)
        → key is saved as-is. Pair must not block on a flaky connection."""
        from research import _pair_prompt_api_keys
        valid_key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
        monkeypatch.setattr("research.resolve_api_key", lambda: "")
        monkeypatch.setattr("research.resolve_gemini_api_key", lambda: "AIza-existing")
        monkeypatch.setattr("research._firebase_db", mock.MagicMock())
        monkeypatch.setattr("research.asyncio.to_thread",
                            _dispatching_to_thread(valid_key, "network_error"))
        before_anthropic = os.environ.get("ANTHROPIC_API_KEY")
        try:
            self._run(_pair_prompt_api_keys("uid-abc"))
            assert os.environ.get("ANTHROPIC_API_KEY") == valid_key
            assert os.environ.get("CUA_API_KEY") == valid_key
        finally:
            if before_anthropic is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
                os.environ.pop("CUA_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = before_anthropic
                os.environ["CUA_API_KEY"] = before_anthropic


# ─────────────────────────────────────────────────────────────────────
# Verifier helpers (Commit 2 — paste-time API check)
# ─────────────────────────────────────────────────────────────────────

class TestVerifyAnthropicKey:
    """`_verify_anthropic_key` returns one of three string statuses.
    The wrapper uses these to decide re-prompt vs save-anyway."""

    def test_empty_key_returns_auth_failed(self, monkeypatch, silent_log):
        from research import _verify_anthropic_key
        assert _verify_anthropic_key("") == "auth_failed"

    def test_successful_models_list_returns_ok(self, monkeypatch, silent_log):
        """models.list returning anything (even an empty page) means the
        key authenticated. _verify_anthropic_key doesn't care about the
        result shape; only whether the SDK throws."""
        from research import _verify_anthropic_key
        fake_anthropic = mock.MagicMock()
        fake_anthropic.AuthenticationError = type("AE", (Exception,), {})
        fake_anthropic.PermissionDeniedError = type("PDE", (Exception,), {})
        fake_anthropic.APITimeoutError = type("AT", (Exception,), {})
        fake_anthropic.APIConnectionError = type("AC", (Exception,), {})
        fake_client = mock.MagicMock()
        fake_client.models.list.return_value = mock.MagicMock()
        fake_anthropic.Anthropic.return_value = fake_client
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
        assert _verify_anthropic_key("sk-ant-anything") == "ok"
        # SDK invoked with the correct timeout + max_retries
        fake_anthropic.Anthropic.assert_called_with(
            api_key="sk-ant-anything", timeout=5.0, max_retries=0)

    def test_authentication_error_returns_auth_failed(self, monkeypatch, silent_log):
        from research import _verify_anthropic_key
        fake_anthropic = mock.MagicMock()
        class _AE(Exception): pass
        class _PDE(Exception): pass
        class _AT(Exception): pass
        class _AC(Exception): pass
        fake_anthropic.AuthenticationError = _AE
        fake_anthropic.PermissionDeniedError = _PDE
        fake_anthropic.APITimeoutError = _AT
        fake_anthropic.APIConnectionError = _AC
        fake_client = mock.MagicMock()
        fake_client.models.list.side_effect = _AE("401 Unauthorized")
        fake_anthropic.Anthropic.return_value = fake_client
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
        assert _verify_anthropic_key("sk-ant-bad") == "auth_failed"

    def test_permission_denied_returns_auth_failed(self, monkeypatch, silent_log):
        """Workspace cap / org-disabled — same UX outcome as bad key."""
        from research import _verify_anthropic_key
        fake_anthropic = mock.MagicMock()
        class _AE(Exception): pass
        class _PDE(Exception): pass
        class _AT(Exception): pass
        class _AC(Exception): pass
        fake_anthropic.AuthenticationError = _AE
        fake_anthropic.PermissionDeniedError = _PDE
        fake_anthropic.APITimeoutError = _AT
        fake_anthropic.APIConnectionError = _AC
        fake_client = mock.MagicMock()
        fake_client.models.list.side_effect = _PDE("403 workspace cap")
        fake_anthropic.Anthropic.return_value = fake_client
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
        assert _verify_anthropic_key("sk-ant-capped") == "auth_failed"

    def test_timeout_returns_network_error(self, monkeypatch, silent_log):
        from research import _verify_anthropic_key
        fake_anthropic = mock.MagicMock()
        class _AE(Exception): pass
        class _PDE(Exception): pass
        class _AT(Exception): pass
        class _AC(Exception): pass
        fake_anthropic.AuthenticationError = _AE
        fake_anthropic.PermissionDeniedError = _PDE
        fake_anthropic.APITimeoutError = _AT
        fake_anthropic.APIConnectionError = _AC
        fake_client = mock.MagicMock()
        fake_client.models.list.side_effect = _AT("timed out")
        fake_anthropic.Anthropic.return_value = fake_client
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
        assert _verify_anthropic_key("sk-ant-slow") == "network_error"


class TestVerifyGeminiKey:
    """`_verify_gemini_key` parses Google's error.details[].reason rather
    than HTTP code alone. API_KEY_INVALID and PERMISSION_DENIED are the
    only re-prompt signals; everything else (quota, transient 5xx, weird
    error shapes) is network_error so the user can save and proceed."""

    def test_empty_key_returns_auth_failed(self, monkeypatch, silent_log):
        from research import _verify_gemini_key
        assert _verify_gemini_key("") == "auth_failed"

    def test_200_returns_ok(self, monkeypatch, silent_log):
        from research import _verify_gemini_key
        fake_requests = mock.MagicMock()
        fake_requests.RequestException = Exception
        fake_resp = mock.MagicMock()
        fake_resp.status_code = 200
        fake_requests.get.return_value = fake_resp
        monkeypatch.setitem(sys.modules, "requests", fake_requests)
        assert _verify_gemini_key("AIza-good") == "ok"
        # 5s timeout is wired
        fake_requests.get.assert_called_with(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": "AIza-good"}, timeout=5.0)

    def test_api_key_invalid_returns_auth_failed(self, monkeypatch, silent_log):
        """Google's structurally-bad-key shape: HTTP 400 with
        error.details[].reason=API_KEY_INVALID."""
        from research import _verify_gemini_key
        fake_requests = mock.MagicMock()
        fake_requests.RequestException = Exception
        fake_resp = mock.MagicMock()
        fake_resp.status_code = 400
        fake_resp.json.return_value = {
            "error": {
                "code": 400,
                "message": "API key not valid.",
                "status": "INVALID_ARGUMENT",
                "details": [
                    {"@type": "...", "reason": "API_KEY_INVALID", "domain": "googleapis.com"},
                ],
            }
        }
        fake_requests.get.return_value = fake_resp
        monkeypatch.setitem(sys.modules, "requests", fake_requests)
        assert _verify_gemini_key("AIza-revoked") == "auth_failed"

    def test_permission_denied_returns_auth_failed(self, monkeypatch, silent_log):
        from research import _verify_gemini_key
        fake_requests = mock.MagicMock()
        fake_requests.RequestException = Exception
        fake_resp = mock.MagicMock()
        fake_resp.status_code = 403
        fake_resp.json.return_value = {
            "error": {"code": 403, "status": "PERMISSION_DENIED", "details": []}
        }
        fake_requests.get.return_value = fake_resp
        monkeypatch.setitem(sys.modules, "requests", fake_requests)
        assert _verify_gemini_key("AIza-scopeless") == "auth_failed"

    def test_429_quota_returns_network_error(self, monkeypatch, silent_log):
        """Quota exceeded ≠ bad key — let the user save and retry later."""
        from research import _verify_gemini_key
        fake_requests = mock.MagicMock()
        fake_requests.RequestException = Exception
        fake_resp = mock.MagicMock()
        fake_resp.status_code = 429
        fake_resp.json.return_value = {
            "error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": []}
        }
        fake_requests.get.return_value = fake_resp
        monkeypatch.setitem(sys.modules, "requests", fake_requests)
        assert _verify_gemini_key("AIza-quota") == "network_error"

    def test_connection_error_returns_network_error(self, monkeypatch, silent_log):
        from research import _verify_gemini_key

        class _CE(Exception):
            pass
        fake_requests = mock.MagicMock()
        fake_requests.RequestException = _CE
        fake_requests.get.side_effect = _CE("ECONNREFUSED")
        monkeypatch.setitem(sys.modules, "requests", fake_requests)
        assert _verify_gemini_key("AIza-offline") == "network_error"


# ─────────────────────────────────────────────────────────────────────
# _pair_prompt_one_key_with_verify (paste + verifier retry loop)
# ─────────────────────────────────────────────────────────────────────

class TestPairPromptOneKeyWithVerify:
    """Verifier wrapper. Skip path is verifier-free; paste path runs
    verifier, re-prompts on auth_failed, saves anyway on network_error."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_skip_never_invokes_verifier(self, monkeypatch, silent_log):
        from research import _pair_prompt_one_key_with_verify

        def _trap(_k):
            raise AssertionError("verifier should not run on skip")

        async def _dispatch(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if "getpass" in name or name == "input":
                return "skip"
            return fn(*args, **kwargs)

        monkeypatch.setattr("research.asyncio.to_thread", _dispatch)
        result = self._run(_pair_prompt_one_key_with_verify(
            "Anthropic", "sk-ant-...", "https://x", verifier=_trap))
        assert result == ""

    def test_ok_returns_key(self, monkeypatch, silent_log):
        from research import _pair_prompt_one_key_with_verify
        valid_key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
        monkeypatch.setattr("research.asyncio.to_thread",
                            _dispatching_to_thread(valid_key, "ok"))
        result = self._run(_pair_prompt_one_key_with_verify(
            "Anthropic", "sk-ant-...", "https://x",
            verifier=lambda k: "ok"))
        assert result == valid_key

    def test_network_error_returns_key_with_warning(self, monkeypatch, silent_log):
        """network_error must not block; key is returned as-is."""
        from research import _pair_prompt_one_key_with_verify
        valid_key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
        monkeypatch.setattr("research.asyncio.to_thread",
                            _dispatching_to_thread(valid_key, "network_error"))
        result = self._run(_pair_prompt_one_key_with_verify(
            "Anthropic", "sk-ant-...", "https://x",
            verifier=lambda k: "network_error"))
        assert result == valid_key

    def test_auth_failed_re_prompts_then_save_anyway_no_returns_empty(
            self, monkeypatch, silent_log):
        """3 auth_failed verifies in a row → asks save-anyway, user says
        N → returns "" (skip). Confirms the escape hatch defaults to no."""
        from research import _pair_prompt_one_key_with_verify
        bad_key = "sk-ant-api03-rejectedrejectedrejectedrejected42424"
        # Sequence: paste, paste, paste, save-anyway? answered N
        inputs = [bad_key, bad_key, bad_key, "N"]

        async def _dispatch(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if "getpass" in name or name == "input":
                return inputs.pop(0)
            return fn(*args, **kwargs)

        monkeypatch.setattr("research.asyncio.to_thread", _dispatch)
        result = self._run(_pair_prompt_one_key_with_verify(
            "Anthropic", "sk-ant-...", "https://x",
            verifier=lambda k: "auth_failed",
            max_attempts=3))
        assert result == ""
        assert inputs == []  # All 4 inputs consumed

    def test_auth_failed_save_anyway_yes_returns_last_key(self, monkeypatch, silent_log):
        """Save-anyway? answered y → last pasted key is returned."""
        from research import _pair_prompt_one_key_with_verify
        bad_key = "sk-ant-api03-stubbornlyrejectedrejectedrejected3434"
        inputs = [bad_key, bad_key, bad_key, "y"]

        async def _dispatch(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if "getpass" in name or name == "input":
                return inputs.pop(0)
            return fn(*args, **kwargs)

        monkeypatch.setattr("research.asyncio.to_thread", _dispatch)
        result = self._run(_pair_prompt_one_key_with_verify(
            "Anthropic", "sk-ant-...", "https://x",
            verifier=lambda k: "auth_failed",
            max_attempts=3))
        assert result == bad_key
        assert inputs == []
