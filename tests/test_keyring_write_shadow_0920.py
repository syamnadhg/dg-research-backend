"""A keyring write that fails must not leave a store nobody reads.

⛔⛔ THE INCIDENT, 2026-09-20, and it was found in a log line the owner asked
about because it looked like noise:

    [WARN] [auth.keystore] keyring write of slot=previous failed, using file:
           Can't store password on keychain: (-25244, 'Unknown Error')

-25244 is `errSecInvalidOwnerEdit` — "Invalid attempt to change the owner of
this item". macOS answers it when the keychain item EXISTS but was created by a
DIFFERENT binary: `set_password` modifies in place, and the item's ACL does not
trust the interpreter now asking. A new venv, a new wheel, a reinstalled Python
is enough.

⛔⛔ WHAT MADE IT MORE THAN NOISE. `set()` already purged the file shadow after a
GOOD keyring write, with a comment saying why: "auth.json can never hold a STALE
token that a later get() would return". The FAILURE path built that very shadow.
And `get()` asks the keyring first, returning its value whenever it is non-empty
— so the fresher copy in the file was unreachable, and the rotation had written
to a store nobody reads.

It was live on the machine that produced the log: `previous:<install>` existed
in the keychain (created 18:39:51Z) AND in auth.json (written fifty minutes
later by this fallback). On the `previous` slot that costs a startup self-heal.
On `current` it is every refresh presenting a dead token until the machine has
to be paired again.

⭐ THE FIX CURES IT RATHER THAN ROUTING AROUND IT. Delete the foreign item and
write again: the new item belongs to the running binary, so the next rotation
does not hit this at all. Only if that ALSO fails do we fall back — and then the
keyring entry is cleared first, because silencing the old value is the only
thing that makes "using the file" true.
"""
from __future__ import annotations

import pytest

from auth import keystore


ACCT = "previous:eda57963a233400ea0359bbd4b6e96e3"
#: The message keyring itself produced on the day. `-25244` renders as "Unknown
#: Error" because keyring has no name for it — which is why the line read as
#: noise for as long as it did.
REAL = "Can't store password on keychain: (-25244, 'Unknown Error')"


class _Keyring:
    """A keyring whose writes fail in a configurable way.

    `owned` models the macOS rule that matters: an item created by another
    binary refuses modification but accepts deletion, so delete-then-set works.
    """

    def __init__(self, *, owned_by_other: bool, deletable: bool = True):
        self.store: dict[str, str] = {}
        self.owned_by_other = owned_by_other
        self.deletable = deletable
        self.sets = 0
        self.deletes = 0

    def set_password(self, service, acct, value):
        self.sets += 1
        if self.owned_by_other and acct in self.store:
            raise Exception(REAL)
        self.store[acct] = value

    def get_password(self, service, acct):
        return self.store.get(acct)

    def delete_password(self, service, acct):
        self.deletes += 1
        if not self.deletable:
            raise Exception("Can't delete password on keychain: (-25244, 'Unknown Error')")
        self.store.pop(acct, None)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(keystore, "_FALLBACK_DIR", tmp_path)
    monkeypatch.setattr(keystore, "_FALLBACK_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(keystore, "_INSTALL_UUID_PATH", tmp_path / "install_uuid")
    monkeypatch.setattr(keystore, "_WIPE_LOG", tmp_path / "keystore-audit.log")
    monkeypatch.setattr(keystore, "_REFRESH_LOCK_PATH", tmp_path / ".refresh.lock")
    return tmp_path


def _use(monkeypatch, kr):
    monkeypatch.setattr(keystore, "_try_keyring", lambda: kr)


INSTALL = "eda57963a233400ea0359bbd4b6e96e3"


# ── the cure ──────────────────────────────────────────────────────────────

def test_a_foreign_item_is_recreated_not_routed_around(home, monkeypatch):
    """⛔ THE HEADLINE. The item exists and belongs to somebody else. Deleting
    and rewriting hands it to us, so the NEXT rotation does not fail either."""
    kr = _Keyring(owned_by_other=True)
    kr.store[ACCT] = "stale-token"
    _use(monkeypatch, kr)

    keystore.set("previous", INSTALL, "fresh-token")

    assert kr.store[ACCT] == "fresh-token"
    assert kr.deletes == 1, "it must delete before rewriting — set_password alone cannot"
    # And nothing landed in the file, because the keyring IS the live store.
    assert not (home / "auth.json").exists() or "previous:" not in (home / "auth.json").read_text()


def test_and_the_value_the_reader_gets_is_the_fresh_one(home, monkeypatch):
    """⛔⛔ THE PROPERTY THAT ACTUALLY BROKE. Before this, `get` returned the
    keyring's stale copy while the fresh one sat unreachable in the file."""
    kr = _Keyring(owned_by_other=True)
    kr.store[ACCT] = "stale-token"
    _use(monkeypatch, kr)

    keystore.set("previous", INSTALL, "fresh-token")
    assert keystore.get("previous", INSTALL) == "fresh-token"


# ── the fallback, made true ───────────────────────────────────────────────

def test_when_the_keyring_cannot_be_fixed_it_is_silenced_first(home, monkeypatch):
    """⛔⛔ THE SHADOW, AND THE ASSERTION REWRITTEN BECAUSE THE FIRST ONE WAS
    SATISFIABLE BY SOMETHING ELSE.

    It used to assert `ACCT not in kr.store` — which the CURE's own delete
    already achieved, so the mutant that removed the silencing survived it. The
    property that cannot be satisfied by anything else is the one the person
    actually has: what does a READER get back? If the keyring is left holding
    the old value, `get()` returns the old value, because `get()` asks it first.
    """
    class _NeverWritable(_Keyring):
        def set_password(self, service, acct, value):
            self.sets += 1
            raise Exception(REAL)

    kr = _NeverWritable(owned_by_other=True)
    kr.store[ACCT] = "stale-token"
    _use(monkeypatch, kr)

    keystore.set("previous", INSTALL, "fresh-token")

    assert keystore.get("previous", INSTALL) == "fresh-token", (
        "the keyring answered with the token nobody wrote")
    assert kr.get_password(None, ACCT) in (None, "")


def test_and_that_holds_even_when_the_write_fails_for_a_reason_deletion_cannot_fix(
        home, monkeypatch):
    """⛔⛔ A LOCKED KEYCHAIN, NOT A FOREIGN OWNER. errSecInteractionNotAllowed
    (-25308) refuses the write with no item to blame — there may be nothing
    stored at all. The fallback must still be readable, and the log must NOT
    claim a stale entry that does not exist."""
    class _Locked(_Keyring):
        def set_password(self, service, acct, value):
            self.sets += 1
            raise Exception("Can't store password on keychain: (-25308, 'Unknown Error')")

    kr = _Locked(owned_by_other=False)
    _use(monkeypatch, kr)

    keystore.set("current", INSTALL, "fresh-token")
    assert keystore.get("current", INSTALL) == "fresh-token"


def test_the_two_stores_are_never_left_disagreeing_in_silence(home, monkeypatch, caplog):
    """⛔⛔ THE ONE GENUINELY BAD STATE: the write fails AND a readable stale
    entry survives. It must be an ERROR naming the remedy — a WARNING is what
    hid this for as long as it hid, and the owner read it as noise for exactly
    that reason."""
    class _Unfixable(_Keyring):
        def set_password(self, service, acct, value):
            self.sets += 1
            raise Exception(REAL)

    kr = _Unfixable(owned_by_other=True, deletable=False)
    kr.store[ACCT] = "stale-token"
    _use(monkeypatch, kr)

    with caplog.at_level("DEBUG", logger="auth.keystore"):
        keystore.set("previous", INSTALL, "fresh-token")

    errs = [r for r in caplog.records if r.levelname == "ERROR"]
    assert errs, "a silent divergence is the failure mode, not a side effect of it"
    said = errs[0].getMessage()
    assert "delete-generic-password" in said, "it must say how to clear it"
    # The token is still persisted — losing it as well would be worse.
    assert keystore._file_load()[ACCT] == "fresh-token"
    # ⛔⛔ WAVE 10.9: AND THE READER GETS IT. The first repair logged this state
    # and left `get()` asking the keyring first — which still answers, with the
    # token the rotation replaced. The stale entry is deliberately still there
    # and still readable, so nothing but the read order can make this pass.
    assert kr.get_password(None, ACCT) == "stale-token"
    assert keystore.get("previous", INSTALL) == "fresh-token", (
        "the keychain's old value outranked the write it could not take")
    # And the sentence says what is now true: the old entry IS readable, but
    # this install no longer returns it — "reads may return an OLD token" was
    # the claim that stopped being true the moment the read order was fixed.
    assert "still readable" in said
    assert "reads may return an OLD token" not in said


def test_and_a_CLEAN_fallback_is_not_reported_as_that(home, monkeypatch, caplog):
    """⛔ THE OTHER DIRECTION, which is how the first draft got it wrong. When
    the keyring ends up silent the fallback is correct and complete; crying
    ERROR over it trains everybody to ignore the one that matters."""
    class _Unwritable(_Keyring):
        def set_password(self, service, acct, value):
            self.sets += 1
            raise Exception(REAL)

    kr = _Unwritable(owned_by_other=True)
    kr.store[ACCT] = "stale-token"
    _use(monkeypatch, kr)

    with caplog.at_level("DEBUG", logger="auth.keystore"):
        keystore.set("previous", INSTALL, "fresh-token")

    assert not [r for r in caplog.records if r.levelname == "ERROR"]
    assert [r for r in caplog.records if r.levelname == "WARNING"]


def test_an_empty_entry_is_silence_because_that_is_what_get_treats_it_as(
        home, monkeypatch, caplog):
    """⛔⛔ THE PROBE MUST MIRROR `get`, NOT THE STORE. `get` does
    `if val: return val` — an entry holding an empty string does NOT win, so a
    keyring left holding one is silent and the file IS authoritative. A probe
    that asked `is not None` instead would call that a live stale token and
    raise a false alarm over a correct fallback. Found by mutation: nothing here
    told the two apart."""
    class _Blanks(_Keyring):
        def set_password(self, service, acct, value):
            self.sets += 1
            raise Exception(REAL)

        def delete_password(self, service, acct):
            # Some backends blank an item they cannot remove.
            self.deletes += 1
            self.store[acct] = ""

    kr = _Blanks(owned_by_other=True)
    kr.store[ACCT] = "stale-token"
    _use(monkeypatch, kr)

    with caplog.at_level("DEBUG", logger="auth.keystore"):
        keystore.set("previous", INSTALL, "fresh-token")

    assert keystore.get("previous", INSTALL) == "fresh-token"
    assert not [r for r in caplog.records if r.levelname == "ERROR"], (
        "an empty entry cannot answer a read, so this fallback is clean")


# ── the number that meant nothing ─────────────────────────────────────────

def test_the_osstatus_is_named_rather_than_printed_as_a_number():
    """⭐ `keyring` renders an unmapped OSStatus as the literal "Unknown Error",
    so the line the owner saw carried a bare `-25244`. The log must say what it
    means — and must KEEP the raw text, or the hint replaces the evidence."""
    out = keystore._oserror_hint(Exception(REAL))
    assert "errSecInvalidOwnerEdit" in out
    assert REAL in out, "the original message must survive the annotation"


@pytest.mark.parametrize("junk", [Exception(""), Exception("no code here"), ValueError("x")])
def test_the_translator_never_invents_a_meaning(junk):
    """An error with no OSStatus in it must come back unchanged. A hint that
    fires on the wrong error is worse than no hint."""
    assert keystore._oserror_hint(junk) == str(junk)


# ── the guards on what must NOT have changed ──────────────────────────────

def test_a_good_write_still_purges_the_file_shadow(home, monkeypatch):
    """The property the failure path used to contradict. It must survive."""
    kr = _Keyring(owned_by_other=False)
    _use(monkeypatch, kr)
    keystore._file_save({ACCT: "old-file-copy"})

    keystore.set("previous", INSTALL, "fresh-token")

    assert ACCT not in keystore._file_load()
    assert kr.store[ACCT] == "fresh-token"
    assert kr.deletes == 0, "a GOOD write must not delete anything"


def test_a_good_write_is_still_one_call(home, monkeypatch):
    """⛔ NO WIDENING. The repair runs only on the failure path; the hot path
    must not grow a delete, a re-read or a second write."""
    kr = _Keyring(owned_by_other=False)
    _use(monkeypatch, kr)
    keystore.set("current", INSTALL, "t")
    assert (kr.sets, kr.deletes) == (1, 0)


def test_no_keyring_at_all_still_goes_straight_to_the_file(home, monkeypatch):
    """Headless Linux / WSL. This path predates the bug and must be untouched."""
    monkeypatch.setattr(keystore, "_try_keyring", lambda: None)
    keystore.set("current", INSTALL, "t")
    assert keystore.get("current", INSTALL) == "t"
