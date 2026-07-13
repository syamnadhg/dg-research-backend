"""Release-hygiene guard (added with the 0.1.5 release).

Catches the exact #947 mistake: a runtime dependency was added to
pyproject.toml ``[project].dependencies`` but the package version was left at an
already-published value. PyPI versions are immutable, so a dep added under a
stale version reaches NO installer — a fresh ``pipx install`` pulls the old
wheel without the dep, and ``superresearch --update`` sees "already latest" and
no-ops. (tinytag was added in #947 while version stayed 0.1.4, which was already
on PyPI without it; that is exactly what this guard prevents recurring.)

Mechanism: a checked-in snapshot (``tests/released_deps.json``) records the
normalized dependency set as of the last release, keyed by the version that
shipped it. This test recomputes the hash from the live pyproject and:

  * if the deps are UNCHANGED, asserts the version still matches the snapshot
    (keeps the snapshot honest);
  * if the deps CHANGED, asserts the version was bumped away from the snapshot
    version — you must bump ``[project].version`` AND re-seed the snapshot in the
    same commit.

Fully offline + deterministic: no PyPI call, no git-history reliance (CI may be
a shallow clone). Normalization (sort + whitespace-collapse + lowercase) means
reordering or reformatting the dependency list is a no-op — only a genuine
change to the published dependency SET moves the hash.

Re-seed after an intentional dep change + version bump::

    python tests/test_release_dep_version_guard.py --seed
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover - repo runs 3.12/3.13/3.14
    import tomli as tomllib  # type: ignore

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_SNAPSHOT = Path(__file__).resolve().parent / "released_deps.json"


def _load_project() -> dict:
    with _PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)["project"]


def normalized_dependency_hash(deps) -> str:
    """Order/format-independent hash of a dependency set.

    Collapses all internal whitespace, lowercases, and sorts, so a reorder or a
    reformat is a no-op and only a real change to the requirement set moves it.
    """
    norm = sorted(re.sub(r"\s+", "", str(d)).lower() for d in deps)
    return hashlib.sha256("\n".join(norm).encode("utf-8")).hexdigest()


def _seed() -> None:
    proj = _load_project()
    payload = {
        "version": proj["version"],
        "deps_sha256": normalized_dependency_hash(proj["dependencies"]),
        "_comment": (
            "Snapshot of [project].dependencies as of this release. Re-seed "
            "(python tests/test_release_dep_version_guard.py --seed) only "
            "together with a [project].version bump."
        ),
    }
    _SNAPSHOT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"seeded {_SNAPSHOT.name} -> version={payload['version']} "
        f"deps_sha256={payload['deps_sha256']}"
    )


def test_dependency_change_requires_version_bump():
    proj = _load_project()
    cur_version = proj["version"]
    cur_hash = normalized_dependency_hash(proj["dependencies"])

    assert _SNAPSHOT.exists(), (
        f"{_SNAPSHOT.name} missing — seed it with "
        f"`python tests/test_release_dep_version_guard.py --seed`"
    )
    snap = json.loads(_SNAPSHOT.read_text(encoding="utf-8"))
    snap_version = snap["version"]
    snap_hash = snap["deps_sha256"]

    if cur_hash == snap_hash:
        assert cur_version == snap_version, (
            f"[project].dependencies are unchanged since the {snap_version} "
            f"release, but pyproject version is now {cur_version} while the "
            f"snapshot still says {snap_version}. Re-seed "
            f"tests/released_deps.json to match, in the same commit as the "
            f"version change."
        )
    else:
        assert cur_version != snap_version, (
            f"[project].dependencies changed since the last release (recorded "
            f"under version {snap_version}) but [project].version was NOT "
            f"bumped. PyPI versions are immutable, so a dependency added under "
            f"{snap_version} reaches no installer. Bump [project].version AND "
            f"re-seed tests/released_deps.json "
            f"(`python tests/test_release_dep_version_guard.py --seed`) in the "
            f"same commit."
        )


if __name__ == "__main__":
    if "--seed" in sys.argv:
        _seed()
    else:
        test_dependency_change_requires_version_bump()
        print("release dep/version guard: OK")
