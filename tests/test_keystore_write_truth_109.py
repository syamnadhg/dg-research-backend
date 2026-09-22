"""Wave 10.9 — a refused keychain write keeps the saved key, and says what is true.

⛔⛔ WHAT THE 2026-09-20 REPAIR LEFT OPEN. That repair (see
`test_keyring_write_shadow_0920.py`) cured the common case — an item another
binary owns is deleted and rewritten — and fell back to the file when it could
not. Three things were still wrong on the paths where the cure does not work:

  M13 — the probe that decides the closing log line answered "nothing there"
        when the keychain could not even be READ (a locked keychain,
        errSecInteractionNotAllowed -25308). The line then said the keyring was
        silent and the file authoritative, while the old entry sat right there.
  M15 — the delete that makes the cure work is the only destructive keystore op
        on an error path, and it wrote no audit record, no log line, and ran
        BEFORE the new token was persisted anywhere. A failed rewrite after a
        good delete, with a file store that also refused, left the machine with
        no key at all.
  M16 — the WARNING called the file store authoritative while `get()` asked the
        keyring FIRST and returned its value — the one the rotation replaced.

⭐ Every test here EXECUTES `set()`/`get()` against a fake keyring whose get,
set and delete each raise a chosen error. No test reads source text.
"""
from __future__ import annotations

import json

import pytest

from auth import keystore

INSTALL = "eda57963a233400ea0359bbd4b6e96e3"
SLOT = "current"
ACCT = f"{SLOT}:{INSTALL}"
STAMP = ACCT + "@fallbackAt"
#: Refuse every write, for as long as the test runs.
ALWAYS = 10 ** 6

#: The texts keyring produces for these OSStatus codes (it has no names for them).
OWNER_SET = "Can't store password on keychain: (-25244, 'Unknown Error')"
OWNER_DEL = "Can't delete password in keychain: (-25244, 'Unknown Error')"
LOCKED_SET = "Can't store password on keychain: (-25308, 'Unknown Error')"
LOCKED_GET = "Can't get password from keychain: (-25308, 'Unknown Error')"
LOCKED_DEL = "Can't delete password in keychain: (-25308, 'Unknown Error')"


class FakeKeyring:
    """A keyring whose get / set / delete each raise a chosen error.

    `refuse_sets` counts down: that many `set_password` calls raise `set_error`,
    then writes succeed. `locked` makes every read raise. `on_delete` runs at
    the moment `delete_password` is called, BEFORE it acts, so a test can see
    what was already on disk when the keychain item was destroyed.
    """

    def __init__(self, *, store=None, refuse_sets=0, set_error=OWNER_SET,
                 delete_error=None, locked=False, on_delete=None):
        self.store: dict[str, str] = dict(store or {})
        self.refuse_sets = refuse_sets
        self.set_error = set_error
        self.delete_error = delete_error
        self.locked = locked
        self.on_delete = on_delete
        self.calls: list[tuple[str, str]] = []

    def set_password(self, service, acct, value):
        self.calls.append(("set", acct))
        if self.refuse_sets:
            self.refuse_sets -= 1
            raise Exception(self.set_error)
        self.store[acct] = value

    def get_password(self, service, acct):
        self.calls.append(("get", acct))
        if self.locked:
            raise Exception(LOCKED_GET)
        return self.store.get(acct)

    def delete_password(self, service, acct):
        self.calls.append(("delete", acct))
        if self.on_delete is not None:
            self.on_delete()
        if self.delete_error:
            raise Exception(self.delete_error)
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


def _audit(home):
    path = home / "keystore-audit.log"
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


def _said(caplog, level=None):
    return [r.getMessage() for r in caplog.records
            if level is None or r.levelname == level]


# ── M13: the probe has three answers, and "could not read" is one of them ──

@pytest.mark.parametrize("stored, locked, want", [
    ("tok", False, "value"),
    ("", False, "empty"),      # `get` does `if val:` — a blank does not win
    (None, False, "empty"),
    ("tok", True, "unknown"),  # the entry is there; we just cannot see it
    (None, True, "unknown"),
])
def test_the_probe_answers_value_empty_or_unknown(stored, locked, want):
    kr = FakeKeyring(store={} if stored is None else {ACCT: stored}, locked=locked)
    assert keystore._keyring_answers(kr, ACCT) == want


def test_a_locked_keychain_is_not_reported_as_a_silent_one(home, monkeypatch, caplog):
    """⛔⛔ THE PIN. A locked keychain refuses the write, refuses the delete and
    refuses the read-back — and the stale entry is still in it. The old probe
    folded the refused read into "nothing there", so the log said the keyring
    was silent and the file authoritative, and the old entry answered the next
    read the moment the keychain unlocked."""
    kr = FakeKeyring(store={ACCT: "stale-token"}, refuse_sets=ALWAYS,
                     set_error=LOCKED_SET, delete_error=LOCKED_DEL, locked=True)
    _use(monkeypatch, kr)

    with caplog.at_level("DEBUG", logger="auth.keystore"):
        keystore.set(SLOT, INSTALL, "fresh-token")

    said = _said(caplog)
    assert not [s for s in said if "authoritative" in s]
    assert not [s for s in said if "holds nothing readable" in s], (
        "an unreadable keychain was described as an empty one")
    errs = _said(caplog, "ERROR")
    assert len(errs) == 1, errs
    assert "could not be read back" in errs[0]
    assert "still readable" not in errs[0], "that is not known either"
    assert "delete-generic-password" in errs[0], "it must say how to clear it"

    # M16, from the same fixture: the keychain unlocks and the old entry is
    # readable again. The reader must still get the token that was written.
    assert keystore.get(SLOT, INSTALL) == "fresh-token"
    kr.locked = False
    assert kr.get_password(None, ACCT) == "stale-token"
    assert keystore.get(SLOT, INSTALL) == "fresh-token"


def test_a_clean_fallback_says_the_keychain_holds_nothing(home, monkeypatch, caplog):
    """⭐ ACCEPT POLARITY for the three-way split: when the delete works and the
    read-back finds nothing, that IS silence — a WARNING, not an ERROR, and it
    says so without calling anything "authoritative"."""
    kr = FakeKeyring(store={ACCT: "stale-token"}, refuse_sets=ALWAYS)
    _use(monkeypatch, kr)

    with caplog.at_level("DEBUG", logger="auth.keystore"):
        keystore.set(SLOT, INSTALL, "fresh-token")

    assert not _said(caplog, "ERROR")
    warns = _said(caplog, "WARNING")
    assert [w for w in warns if "holds nothing readable" in w], warns
    assert not [s for s in _said(caplog) if "authoritative" in s]
    assert keystore.get(SLOT, INSTALL) == "fresh-token"


# ── M16: the copy the keyring refused is the one a reader gets ────────────

@pytest.mark.parametrize("blob, want", [
    ({ACCT: "file", STAMP: "2026-09-21T00:00:00+00:00"}, "file"),
    ({ACCT: "file"}, None),                       # legacy: never re-routed
    ({STAMP: "2026-09-21T00:00:00+00:00"}, None),  # a stamp with no copy
    ({ACCT: "file", STAMP: ""}, None),
    ({"previous:" + INSTALL: "x",
      "previous:" + INSTALL + "@fallbackAt": "t", ACCT: "file"}, None),  # another slot's stamp
    ({}, None),
    (None, None),                                 # unreadable file
    (["not", "a", "dict"], None),
])
def test_only_a_stamped_copy_outranks_the_keyring(blob, want):
    assert keystore._refused_write_copy(blob, ACCT) == want


def test_an_unstamped_file_copy_keeps_the_keyring_first(home, monkeypatch):
    """⛔ NO RE-ROUTING OF OLDER STATE. A file copy from before the stamp existed
    says nothing about which store is newer, so it keeps the order it had."""
    _use(monkeypatch, FakeKeyring(store={ACCT: "keyring-token"}))
    keystore._file_save({ACCT: "legacy-file-copy"})
    assert keystore.get(SLOT, INSTALL) == "keyring-token"


@pytest.mark.parametrize("blob", [
    {STAMP: "2026-09-21T00:00:00+00:00"},
    {ACCT: "", STAMP: "2026-09-21T00:00:00+00:00"},
])
def test_a_stamp_with_no_usable_copy_does_not_hide_the_keyring(home, monkeypatch, blob):
    """An older binary's purge pops the account and not the stamp it never knew
    about. That stamp alone must not blank a read the keyring can answer."""
    _use(monkeypatch, FakeKeyring(store={ACCT: "keyring-token"}))
    keystore._file_save(blob)
    assert keystore.get(SLOT, INSTALL) == "keyring-token"


def test_an_unreadable_auth_json_does_not_slow_or_change_a_keyring_read(
        home, monkeypatch):
    """⛔ The stamp check runs before EVERY keyring read, so it must not inherit
    `_file_load`'s ~1.4s retry: an auth.json this user cannot read would put
    that on every `get` of a machine whose keyring works."""
    _use(monkeypatch, FakeKeyring(store={ACCT: "keyring-token"}))
    keystore._file_save({ACCT: "file", STAMP: "t"})
    real_read = type(home / "auth.json").read_text

    def _denied(self, *a, **k):
        if self.name == "auth.json":
            raise PermissionError(13, "Permission denied")
        return real_read(self, *a, **k)

    monkeypatch.setattr(type(home / "auth.json"), "read_text", _denied)
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))
    assert keystore.get(SLOT, INSTALL) == "keyring-token"
    assert slept == []


def test_a_good_write_after_a_refusal_takes_the_read_back(home, monkeypatch):
    """⭐ ACCEPT POLARITY for M16: the stamp is a statement about the LAST write.
    Once a keyring write succeeds, the keyring is the newer store again and the
    file must stop outranking it — copy and stamp both gone."""
    kr = FakeKeyring(store={ACCT: "stale-token"}, refuse_sets=ALWAYS,
                     delete_error=OWNER_DEL)
    _use(monkeypatch, kr)
    keystore.set(SLOT, INSTALL, "fresh-token")
    assert keystore._file_load()[STAMP], "a refused write must be stamped"
    assert keystore.get(SLOT, INSTALL) == "fresh-token"

    kr.refuse_sets = 0  # the owner ran the remedy; writes work again
    keystore.set(SLOT, INSTALL, "newer-token")

    assert kr.store[ACCT] == "newer-token"
    assert keystore.get(SLOT, INSTALL) == "newer-token"
    blob = keystore._file_load()
    assert ACCT not in blob and STAMP not in blob, blob


def test_a_good_write_also_clears_a_stamp_left_on_its_own(home, monkeypatch):
    _use(monkeypatch, FakeKeyring())
    keystore._file_save({STAMP: "2026-09-21T00:00:00+00:00", "other:x": "keep"})
    keystore.set(SLOT, INSTALL, "tok")
    assert keystore._file_load() == {"other:x": "keep"}


def test_delete_takes_the_stamp_with_the_copy(home, monkeypatch):
    kr = FakeKeyring(store={ACCT: "stale-token"}, refuse_sets=ALWAYS,
                     delete_error=OWNER_DEL)
    _use(monkeypatch, kr)
    keystore.set(SLOT, INSTALL, "fresh-token")
    kr.delete_error = None

    keystore.delete(SLOT, INSTALL)

    blob = keystore._file_load()
    assert ACCT not in blob and STAMP not in blob, blob
    assert keystore.get(SLOT, INSTALL) is None


def test_a_refused_rotation_still_hands_the_next_refresh_the_new_token(
        home, monkeypatch):
    """⛔⛔ THE CONSUMER. `credentials.py` writes `pending` then promotes; on a
    keychain that refuses every write and every delete, the old `current` stays
    readable in it. The next refresh reads `current` — and must get the token
    this rotation produced, not the one it replaced."""
    kr = FakeKeyring(store={ACCT: "old-current"}, refuse_sets=ALWAYS,
                     set_error=LOCKED_SET, delete_error=LOCKED_DEL)
    _use(monkeypatch, kr)

    keystore.set("pending", INSTALL, "rotated")
    keystore.promote_pending(INSTALL)

    assert kr.store[ACCT] == "old-current", "the fixture must keep the old value readable"
    assert keystore.get("current", INSTALL) == "rotated"
    assert keystore.get("previous", INSTALL) == "old-current"
    assert keystore.try_recover(INSTALL) == ("current", "rotated")


# ── M15: the delete is audited, and it never runs before the token is safe ─

def test_the_delete_a_refused_write_makes_is_audited_first(home, monkeypatch, caplog):
    """⛔⛔ THE PIN. The foreign-item cure: the first write is refused (-25244),
    the item is deleted, the rewrite succeeds. The delete removes the item a
    later read would have used, so it gets the durable record `clear_all` gets —
    one line, naming the event, the slot and the refusal, on disk BEFORE the
    delete runs. `clear_all` is never called on this path, so nothing else can
    have written it."""
    seen = {}
    kr = FakeKeyring(store={ACCT: "stale-token"}, refuse_sets=1,
                     on_delete=lambda: seen.setdefault("audit", _audit(home)))
    _use(monkeypatch, kr)

    with caplog.at_level("DEBUG", logger="auth.keystore"):
        keystore.set(SLOT, INSTALL, "fresh-token")

    assert kr.store[ACCT] == "fresh-token", "the cure itself must still work"
    lines = _audit(home)
    assert len(lines) == 1, lines
    rec = lines[0]
    assert rec["event"] == "keyring-delete-before-rewrite"
    assert rec["slot"] == SLOT
    assert rec["install"] == INSTALL[:8]
    assert "errSecInvalidOwnerEdit" in rec["reason"]
    assert seen["audit"] == lines, "the record must be on disk BEFORE the delete"
    # A delete that worked is not reported as one that failed.
    assert not [w for w in _said(caplog) if "could not delete" in w]


def test_writes_that_destroy_nothing_audit_nothing(home, monkeypatch):
    """⭐ ACCEPT POLARITY: the hot path and the no-keyring path delete nothing,
    so they must not write the audit line — a record on every rotation would
    bury the one that matters."""
    _use(monkeypatch, FakeKeyring())
    keystore.set(SLOT, INSTALL, "tok")
    monkeypatch.setattr(keystore, "_try_keyring", lambda: None)
    keystore.set("previous", INSTALL, "tok2")
    assert _audit(home) == []


def test_clear_all_still_records_itself_as_clear_all(home, monkeypatch):
    monkeypatch.setattr(keystore, "_try_keyring", lambda: None)
    keystore.clear_all(INSTALL, reason="unpair")
    (rec,) = _audit(home)
    assert (rec["event"], rec["reason"], rec["slot"]) == ("clear_all", "unpair", None)


def test_the_new_token_is_on_disk_before_the_old_one_is_deleted(home, monkeypatch):
    """⛔⛔ "STOPS DESTROYING THE SAVED KEY". The delete used to run first and
    the file write last, so a rewrite that failed after a good delete left the
    credential in neither store until the tail ran — and nowhere at all if the
    tail raised. The new token must already be in the file, stamped, at the
    moment the keychain item is destroyed."""
    seen = {}
    kr = FakeKeyring(store={ACCT: "stale-token"}, refuse_sets=ALWAYS,
                     on_delete=lambda: seen.setdefault("file", keystore._file_load()))
    _use(monkeypatch, kr)

    keystore.set(SLOT, INSTALL, "fresh-token")

    assert seen["file"].get(ACCT) == "fresh-token", seen
    assert seen["file"].get(STAMP), seen


def test_when_the_file_cannot_take_it_the_keychain_entry_is_left_alone(
        home, monkeypatch):
    """⛔⛔ AND THE CASE THAT ORDER EXISTS FOR. The keyring refuses the write and
    the file store cannot take it either. The old code deleted the keychain
    entry anyway — the last copy of anything — then raised. Now nothing is
    deleted, nothing is audited, and the caller still sees the failure."""
    kr = FakeKeyring(store={ACCT: "saved-token"}, refuse_sets=ALWAYS)
    _use(monkeypatch, kr)

    def _full(blob):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(keystore, "_file_save", _full)
    with pytest.raises(OSError):
        keystore.set(SLOT, INSTALL, "fresh-token")

    assert ("delete", ACCT) not in kr.calls
    assert kr.store[ACCT] == "saved-token"
    assert _audit(home) == []


def test_a_delete_that_fails_says_so(home, monkeypatch, caplog):
    """The old `contextlib.suppress` swallowed the delete's outcome whole."""
    kr = FakeKeyring(store={ACCT: "stale-token"}, refuse_sets=ALWAYS,
                     delete_error=OWNER_DEL)
    _use(monkeypatch, kr)

    with caplog.at_level("DEBUG", logger="auth.keystore"):
        keystore.set(SLOT, INSTALL, "fresh-token")

    warns = _said(caplog, "WARNING")
    assert [w for w in warns
            if "could not delete" in w and "errSecInvalidOwnerEdit" in w], warns


# ── the purge that the stamp now depends on ───────────────────────────────

def test_a_good_write_that_cannot_drop_its_file_copy_says_so(home, monkeypatch, caplog):
    """⛔ A stamped copy OUTRANKS the keyring, so a purge that fails after a good
    write is the one way a newer keychain value can lose a read. It was
    swallowed in silence; it must at least be said."""
    kr = FakeKeyring()
    _use(monkeypatch, kr)
    keystore._file_save({ACCT: "older", STAMP: "2026-09-21T00:00:00+00:00"})

    def _denied(blob):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(keystore, "_file_save", _denied)
    with caplog.at_level("DEBUG", logger="auth.keystore"):
        keystore.set(SLOT, INSTALL, "tok")  # must not raise

    assert kr.store[ACCT] == "tok"
    assert [w for w in _said(caplog, "WARNING") if "could not be removed" in w]


def test_a_good_write_with_nothing_to_purge_is_silent(home, monkeypatch, caplog):
    kr = FakeKeyring()
    _use(monkeypatch, kr)
    with caplog.at_level("DEBUG", logger="auth.keystore"):
        keystore.set(SLOT, INSTALL, "tok")
    assert _said(caplog) == []
    assert kr.calls == [("set", ACCT)]
