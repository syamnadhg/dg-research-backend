"""No consumer-mailbox addresses in source.

History: commit `5913a13` removed real personal addresses from `research.py`.
Review of the DGOPS-7335 snapshot PR then found two survivors that were merely
*illustrative* — a banner-format comment in `research.py` and a `_mask_email`
fixture in `agent/tests/test_bridge_routes.py`. Both were fake, and that is the
problem: a plausible-looking gmail address is indistinguishable from a real leak
to the next person grepping this tree during an audit, so it costs someone a
real investigation every time.

The rule is therefore about the SHAPE, not about whether a given address is
genuine: examples use RFC 2606 reserved domains (`example.com` / `example.org` /
`example.net`, or a `.invalid` / `.test` / `.example` TLD), which cannot be
registered and so can never be mistaken for a person's mailbox.

Scope is source we author. Vendored trees are skipped, and the scan asserts it
actually visited a meaningful number of files — a path-glob that silently
matched nothing would otherwise make this test pass forever.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Free/consumer mail providers. Corporate domains are deliberately NOT listed:
# `distributedglobal.com` and `dg-eng.com` appear legitimately as *hostnames* in
# the F4 security deny-list, and this pattern only matches an address shape
# (local-part + @) so those entries do not trip it.
_CONSUMER_MAIL = (
    "gmail.com", "googlemail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "live.com", "aol.com", "icloud.com", "me.com", "protonmail.com", "proton.me",
    "gmx.com", "mail.ru", "yandex.ru", "qq.com", "163.com",
)
_ADDRESS_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@(?:" + "|".join(re.escape(d) for d in _CONSUMER_MAIL) + r")\b",
    re.IGNORECASE,
)

_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".ruff_cache", ".mypy_cache", "build", "dist", ".eggs", "site-packages",
}
_SCAN_SUFFIXES = {".py", ".md", ".toml", ".yml", ".yaml", ".json", ".txt", ".sh", ".ps1"}


def _source_files() -> list[Path]:
    out: list[Path] = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in _SCAN_SUFFIXES:
            continue
        if any(part in _SKIP_DIRS or part.endswith(".egg-info") for part in p.relative_to(ROOT).parts):
            continue
        out.append(p)
    return out


def test_the_scan_actually_covers_the_tree() -> None:
    """Guard against the guard: a broken glob must fail loudly, not pass empty."""
    files = _source_files()
    assert len(files) > 200, (
        f"only {len(files)} files matched — the scan below would be vacuous. "
        "Check _SCAN_SUFFIXES / _SKIP_DIRS against the current layout."
    )
    names = {f.name for f in files}
    for expected in ("research.py", "pyproject.toml", "requirements.txt"):
        assert expected in names, f"{expected} was not scanned — the walk is wrong"


def test_no_consumer_mailbox_addresses_in_source() -> None:
    hits: list[str] = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in _ADDRESS_RE.finditer(line):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}: {match.group(0)}")
    assert not hits, (
        "consumer-mailbox address literal(s) found. Even as an example this reads as a "
        "real person's address to anyone auditing this tree — use an RFC 2606 reserved "
        "domain (user@example.com) instead:\n  " + "\n  ".join(hits)
    )
