"""Wave 4: a support code read aloud resolves.

⛔⛔ MEASURED ON A REAL CODE, 2026-08-22. The owner quoted `1ZOFGVED` and it
resolved to nothing. The code was `1Z0FGVED` — a zero. Crockford base32 drops the
letters O, I and L precisely so a code read over a call cannot come back as a
different one, and **nothing anywhere performed the substitution that makes that
true**. Dropping the letter from the alphabet, on its own, buys nothing: it turns
a recoverable mis-read into a hard refusal. The comment on both sides of this
product claimed the property; neither side implemented it.

⛔⛔ AND THE OBVIOUS PLACE TO FIX IT IS THE WRONG ONE. Every support code inside
this product is a RENDEZVOUS key minted by the other side: the app mints it,
writes the command carrying it, and watches `users/{uid}/logBundles/{code}` for
the row this machine writes back. Normalising it at either wire boundary would
write the row under a different id than the app is watching — and the app reads a
missing row as "this build is too old to understand the request". So the
normaliser is for LOOKING A CODE UP, the two acceptors stay exact, and a test
below holds them there.

⭐ The lookup that failed lives on our side of a support call, so this is where it
goes: `--send-logs` leaves every archive in `outgoing/support-<CODE>.zip`, which
means the machine that sent one can still produce it from the code alone.

Run: pytest tests/test_support_code_lookup_0822.py -v
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research  # noqa: E402
from conftest import code_only_deep  # noqa: E402


N = research._normalize_support_code
REAL = "1Z0FGVED"          # the owner's actual code
MISREAD = "1ZOFGVED"       # the owner's reading of it


# ══════════════════════════════════════════════════════════════════════════
#  1. the substitution the alphabet was chosen for
# ══════════════════════════════════════════════════════════════════════════

class TestTheLettersTheAlphabetLeavesOut:

    def test_the_owners_own_mis_read_resolves_to_the_code_that_exists(self):
        assert N(MISREAD) == REAL

    @pytest.mark.parametrize("typed,minted", [
        ("OOOOOOOO", "00000000"),
        ("IIIIIIII", "11111111"),
        ("LLLLLLLL", "11111111"),
        ("OIL12345", "01112345"),
    ])
    def test_each_confusable_maps_to_its_digit(self, typed, minted):
        assert N(typed) == minted

    def test_the_letter_u_is_left_alone(self):
        """⛔ Crockford drops U to avoid accidental obscenity, not because it
        looks like anything — there is no digit to map it to. Inventing one would
        silently accept a code that was never minted, which is worse than
        refusing: it sends a support call after an archive that cannot exist."""
        assert "U" not in research._SUPPORT_CODE_CONFUSABLES
        assert N("UUUUUUUU") == ""

    def test_no_mapped_letter_can_ever_be_minted(self):
        """⛔⛔ THE LOAD-BEARING INVARIANT. The substitution is only safe because
        a real code cannot contain the letters it rewrites. Put one back in the
        alphabet and this normaliser starts corrupting codes that were minted
        correctly."""
        assert not (set(research._SUPPORT_CODE_CONFUSABLES)
                    & set(research._SUPPORT_CODE_ALPHABET))

    def test_every_substitution_lands_inside_the_alphabet(self):
        for target in research._SUPPORT_CODE_CONFUSABLES.values():
            assert target in research._SUPPORT_CODE_ALPHABET, target

    def test_the_shape_check_and_the_alphabet_describe_the_same_letters(self):
        """⛔ Two spellings of one alphabet — a regex and a string — is how a
        character becomes mintable and unacceptable at the same time."""
        import string
        for ch in string.digits + string.ascii_uppercase:
            accepted = bool(research._SUPPORT_CODE_RE.match(ch * 8))
            mintable = ch in research._SUPPORT_CODE_ALPHABET
            assert accepted == mintable, ch


class TestWhatPeopleTypeAroundTheCode:

    @pytest.mark.parametrize("typed", [
        "1z0fgved", "1Z0F-GVED", "1Z0F GVED", " 1Z0FGVED ", "1z0f_gved",
        "1Z0F.GVED", "1z0f-gved\n", "1Z0F·GVED", "1Z0F—GVED",
    ])
    def test_case_and_separators_do_not_stop_a_code_resolving(self, typed):
        assert N(typed) == REAL

    def test_a_minted_code_always_survives_the_normaliser_unchanged(self):
        """⭐ The property that matters most: normalising must be a no-op on
        every code this machine can actually produce."""
        for _ in range(400):
            code = research._mint_support_code()
            assert N(code) == code, code

    @pytest.mark.parametrize("bad", [
        "", None, "1Z0FGVE", "1Z0FGVEDX", "1Z0FGVE!", "1Z0FGVEU", 12345,
        "        ", "----------------", ["1Z0FGVED"],
    ])
    def test_anything_that_is_still_not_a_code_is_refused(self, bad):
        assert N(bad) == ""

    def test_a_non_string_that_spells_a_code_is_read_as_one(self):
        """⭐ It stringifies rather than raising: this is called on whatever a
        support conversation produced, and a TypeError inside a lookup is a
        worse answer than a code."""
        assert N(12345678) == "12345678"


# ══════════════════════════════════════════════════════════════════════════
#  2. the boundaries that must NOT normalise
# ══════════════════════════════════════════════════════════════════════════

def test_the_two_wire_boundaries_stay_exact():
    """⛔⛔ THE DECISION, PINNED. A support code arriving over the wire is a
    rendezvous key the app minted and is watching. Rewriting it here writes the
    status row under an id nothing is watching, and the app reads a missing row
    as "your build is too old" — so a mis-typed code would become a silent lie
    about the software's version instead of a lookup failure."""
    for fn in (research._handle_send_logs_command,
               research._upload_log_bundle_via_storage_rest):
        src = code_only_deep(fn)
        assert "_normalize_support_code" not in src, (
            f"{fn.__name__} normalises a code the app is watching under its "
            f"original spelling")
        assert "_SUPPORT_CODE_RE.match" in src, (
            f"{fn.__name__} no longer checks the code's shape at all")


def test_the_rule_is_written_once():
    """The script, the normaliser and the reply all read one map."""
    src = inspect.getsource(research)
    assert src.count("_SUPPORT_CODE_CONFUSABLES = ") == 1
    script = Path(inspect.getsourcefile(research)).parent / "scripts" / "find_support_bundle.py"
    body = script.read_text(encoding="utf-8")
    assert "research.find_local_support_bundle(" in body
    assert '"O": "0"' not in body, (
        "the script carries its own copy of the substitution rule")


# ══════════════════════════════════════════════════════════════════════════
#  3. the lookup itself
# ══════════════════════════════════════════════════════════════════════════

def _outgoing(tmp_path, *codes):
    d = tmp_path / "outgoing"
    d.mkdir()
    for c in codes:
        (d / f"support-{c}{research.BUNDLE_SUFFIX}").write_bytes(b"PK\x03\x04zip")
    return d


class TestFindingTheBundleTheCodeNames:

    def test_a_mis_read_code_finds_the_archive_that_exists(self, tmp_path):
        d = _outgoing(tmp_path, REAL, "9X3WJPD4")
        got = research.find_local_support_bundle(MISREAD, root=d)
        assert got["code"] == REAL
        assert got["path"].endswith(f"support-{REAL}.zip")
        assert got["sizeBytes"] > 0

    def test_a_code_this_machine_never_sent_is_a_plain_no(self, tmp_path):
        d = _outgoing(tmp_path, "9X3WJPD4")
        got = research.find_local_support_bundle(MISREAD, root=d)
        assert got["code"] == REAL
        assert got["path"] == ""
        assert got["available"] == ["9X3WJPD4"], (
            "a bare no leaves the reader unable to tell 'wrong machine' from "
            "'wrong code'")

    def test_a_code_sharing_a_prefix_with_another_is_not_confused_for_it(self, tmp_path):
        """⛔ FOUND BY MUTATION. Every earlier fixture used codes that differ in
        their first characters, so a lookup matching on a PREFIX resolved to the
        right archive anyway and the tests said nothing. Handing a support call
        the wrong machine's bundle is worse than handing it none."""
        d = _outgoing(tmp_path, "1Z0FGVED", "1Z0FGVEE", "1Z000000")
        got = research.find_local_support_bundle("1zofgvee", root=d)
        assert got["code"] == "1Z0FGVEE"
        assert Path(got["path"]).name == "support-1Z0FGVEE.zip"

    def test_something_that_is_not_a_code_never_matches_a_file(self, tmp_path):
        d = _outgoing(tmp_path, REAL)
        got = research.find_local_support_bundle("nope", root=d)
        assert got["code"] == ""
        assert got["path"] == ""
        assert got["available"] == [REAL], "the listing is still worth having"

    def test_a_missing_folder_is_an_empty_answer_not_an_exception(self, tmp_path):
        got = research.find_local_support_bundle(REAL, root=tmp_path / "gone")
        assert got["path"] == "" and got["available"] == []

    def test_the_reply_says_what_was_typed_and_where_it_looked(self, tmp_path):
        d = _outgoing(tmp_path)
        got = research.find_local_support_bundle("  1z0f-gved ", root=d)
        assert got["typed"] == "  1z0f-gved "
        assert got["searched"] == str(d)

    def test_only_a_real_letter_substitution_is_announced(self, tmp_path):
        """⛔ A reply that named the letter rule on every normalisation would be
        claiming a substitution that did not happen — the same species of untrue
        copy this wave exists to remove. Case and dashes are not that."""
        d = _outgoing(tmp_path, REAL)
        assert research.find_local_support_bundle("1z0f-gved", root=d)["remapped"] == []
        assert research.find_local_support_bundle(MISREAD, root=d)["remapped"] == ["O→0"]

    def test_the_folder_it_searches_is_the_one_send_logs_writes_to(self):
        """⛔ Two opinions about where a bundle lands and the lookup answers
        about a directory nothing writes."""
        writer = code_only_deep(research.cmd_send_logs)
        assert '_logs_root() / "outgoing"' in writer
        assert '_logs_root() / "outgoing"' in code_only_deep(
            research.find_local_support_bundle)

    def test_files_that_are_not_bundles_are_not_offered_as_codes(self, tmp_path):
        d = _outgoing(tmp_path, REAL)
        (d / "notes.txt").write_text("x", encoding="utf-8")
        (d / "support-partial.tmp").write_text("x", encoding="utf-8")
        got = research.find_local_support_bundle(REAL, root=d)
        assert got["available"] == [REAL]
