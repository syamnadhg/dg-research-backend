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
    (users/{uid}/…) or a device queue it is a member of (devices/{id}/queue) or a
    read query (:runQuery) — exactly what a normal account client may already do.
    This is the load-bearing 'no rules change' evidence."""
    src = (FACADE_DIR / "firestore_rest.py").read_text(encoding="utf-8")
    paths = re.findall(r"config\.FIRESTORE_BASE\}(\S*)", src)
    assert paths, "expected to find FIRESTORE_BASE path templates"
    for p in paths:
        assert (
            p.startswith("/users/{uid}")
            or p.startswith("/devices/{device_id}/queue")
            or p.startswith(":runQuery")
        ), f"Firestore path escapes account scope: {p!r}"


def test_secret_store_isolated_from_device_keystore():
    assert config.STORE_SERVICE == "super-agent"
    assert config.STORE_SERVICE != "super-research"
    assert config.STORE_DIR_NAME == ".super-agent"
