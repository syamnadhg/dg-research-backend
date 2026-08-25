"""The "app plane unchanged" proof (recipe P7 gate).

Automated evidence that research-facade is fully self-contained and changes
NOTHING about the existing Super Research app/backend:

  * no facade module imports research / research_app / research_automate;
  * the standalone skill client (sr.py) is stdlib-only (no facade, no requests);
  * every Firestore WRITE targets only the caller's own tree (users/{uid}/…) or
    a device queue it is a member of (devices/{id}/queue) — i.e. exactly what a
    normal account client may already write, no rules change;
  * the secret store is isolated from the device daemon's keystore.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import facade
from facade import config

FACADE_DIR = Path(facade.__file__).parent
FORBIDDEN_MODULES = {"research", "research_app", "research_automate"}


def _facade_py_files():
    # Package modules only (exclude the standalone skill bundle, checked separately).
    return [p for p in FACADE_DIR.glob("*.py")]


def _imported_top_modules(path: Path) -> set[str]:
    """Top-level module names this file imports (AST — ignores comments/strings)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # absolute import only
                mods.add(node.module.split(".")[0])
    return mods


def test_no_facade_module_imports_app_or_automate():
    for f in _facade_py_files():
        bad = _imported_top_modules(f) & FORBIDDEN_MODULES
        assert not bad, f"{f.name} imports forbidden module(s): {bad}"


def test_facade_third_party_deps_are_only_requests_and_keyring():
    # The whole point of the REST/keyring reimplementation: no google/firebase SDK,
    # no coupling to the app's dependency set.
    allowed_third_party = {"requests", "keyring"}
    import sys
    stdlib = set(getattr(sys, "stdlib_module_names", set()))
    for f in _facade_py_files():
        for mod in _imported_top_modules(f):
            if mod == "facade" or mod in stdlib:
                continue
            assert mod in allowed_third_party, f"{f.name} pulls unexpected dep: {mod}"


def test_sr_client_is_stdlib_only():
    sr = FACADE_DIR / "skill" / "scripts" / "sr.py"
    mods = _imported_top_modules(sr)
    import sys
    stdlib = set(getattr(sys, "stdlib_module_names", set()))
    extra = {m for m in mods if m not in stdlib}
    # standalone in the runtime: no facade import, no requests/keyring
    assert extra == set(), f"sr.py is not stdlib-only: {extra}"


def test_all_firestore_paths_are_account_scoped():
    """EVERY Firestore path the client builds stays under the caller's own tree
    (users/{uid}/…) or a collection on a device it is a member of, or a read
    query (:runQuery) — exactly what a normal account client may already do.
    This is the load-bearing 'no rules change' evidence.

    ⭐ 2026-08-25 (wave 8L) — `devices/{id}/commands` JOINS THE LIST, and the
    claim above survives intact rather than being weakened to fit. That
    collection has been writable by a device's owner AND its sharers since long
    before this agent existed; what is newer is only that one of its actions,
    `send-logs-selected`, was opened to sharers on 2026-08-24, and that clause
    is in the deployed ruleset already because the web app's own picker needs
    it. So no rule moved for this wave — the allowlist here was simply narrower
    than the boundary it was standing in for.

    ⛔ AND THE PATH IS NOT THE WHOLE PERMISSION HERE, which is why the next
    test exists. A device command's ACTION decides what may be asked for: two
    of the three send-logs names mean "the whole machine" and stay owner-only.
    A path check alone would call all three the same thing.
    """
    src = (FACADE_DIR / "firestore_rest.py").read_text(encoding="utf-8")
    paths = re.findall(r"config\.FIRESTORE_BASE\}(\S*)", src)
    assert paths, "expected to find FIRESTORE_BASE path templates"
    for p in paths:
        assert (
            p.startswith("/users/{uid}")
            or p.startswith("/devices/{device_id}/queue")
            or p.startswith("/devices/{device_id}/commands")
            or p.startswith(":runQuery")
        ), f"Firestore path escapes account scope: {p!r}"


def test_this_client_can_never_choose_a_device_command_for_itself():
    """The action a device command carries IS its permission, so the module
    that talks to Firestore must not be able to pick one.

    ⛔⛔ A DEFAULT WOULD BE A CHOICE MADE IN THE WRONG PLACE. `send-logs` and
    `send-logs-limited` both mean "everything this computer has ever done, for
    everyone who uses it"; only `send-logs-selected` is scoped to the person
    asking. A default here — however sensible-looking — would be a
    whole-machine request that every future caller inherits without naming it,
    and on the owner's own machine it would work perfectly. The caller names
    the action, every time, and `bridge.py` is where that name is pinned.
    """
    import inspect

    from facade.firestore_rest import FirestoreRest

    sig = inspect.signature(FirestoreRest.write_device_command)
    action = sig.parameters["action"]
    assert action.default is inspect.Parameter.empty, (
        "write_device_command must not default its action — see this test's docstring")
    src = (FACADE_DIR / "firestore_rest.py").read_text(encoding="utf-8")
    assert "send-logs" not in src, (
        "no send-logs action name may be written into the Firestore client itself")


def test_secret_store_isolated_from_device_keystore():
    assert config.STORE_SERVICE == "super-agent"
    assert config.STORE_SERVICE != "super-research"
    assert config.STORE_DIR_NAME == ".super-agent"
