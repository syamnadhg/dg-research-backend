"""macOS launchd supervisor log paths must be TCC-safe (live incident 2026-07-19).

launchd opens a service's StandardOutPath/StandardErrorPath ITSELF before exec.
That open is attributed to launchd — not the target binary — so no user TCC
grant (not even Full Disk Access on the python interpreter) can allow it into a
protected folder (~/Downloads, ~/Desktop, ~/Documents, iCloud). With a source
checkout under ~/Downloads, the agent died at spawn-init with exit code 78
(EX_CONFIG), EMPTY logs, and a 10s respawn loop — the device never came online
after --pair even though pairing itself succeeded.

Fix: `_arm_supervisor_macos` writes supervisor logs to ~/Library/Logs/
SuperResearch (platform-canonical, always launchd-openable) instead of
script_dir/logs. Installed (pipx) builds benefit too — script_dir/logs sat
inside site-packages, where an `--update` reinstall wiped them. The function
also WARNs when the checkout itself is under a TCC-protected folder (the
python-attributed reads there still need a one-time per-binary grant).

Run:  pytest tests/test_macos_launchd_tcc_logs.py -v
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research


MAC_SRC = inspect.getsource(research._arm_supervisor_macos)


def test_macos_log_dir_is_library_logs_not_script_dir():
    assert 'Path.home() / "Library" / "Logs" / "SuperResearch"' in MAC_SRC
    # The old TCC-broken location must be gone.
    assert 'log_dir = script_dir / "logs"' not in MAC_SRC


def test_macos_plist_template_still_wires_log_dir():
    # The template must keep deriving both std paths from log_dir, so the
    # relocation actually reaches the plist.
    assert "{log_dir / 'supervisor.out.log'}" in MAC_SRC
    assert "{log_dir / 'supervisor.err.log'}" in MAC_SRC
    assert "<key>StandardOutPath</key>" in MAC_SRC
    assert "<key>StandardErrorPath</key>" in MAC_SRC


def test_macos_log_dir_mkdir_uses_parents():
    # ~/Library/Logs/SuperResearch may not exist yet; a bare mkdir would fail
    # and abort arming.
    assert "log_dir.mkdir(parents=True, exist_ok=True)" in MAC_SRC


def test_macos_warns_on_tcc_protected_checkout():
    # A checkout under Downloads/Desktop/Documents still needs a per-binary
    # grant for the python-attributed reads — the arm must say so loudly
    # instead of letting the agent die silently at first spawn.
    assert '"Downloads", "Desktop", "Documents"' in MAC_SRC
    # (the message f-string wraps mid-phrase, so pin a stable fragment)
    assert "grant Full Disk" in MAC_SRC


def test_linux_unit_untouched_by_macos_relocation():
    # The relocation is macOS-only: Linux has no TCC; its systemd unit keeps
    # its own log_dir wiring.
    linux_fn = getattr(research, "_arm_supervisor_linux", None)
    if linux_fn is None:
        return  # naming drift — the macOS pins above are the contract
    linux_src = inspect.getsource(linux_fn)
    assert "Library" not in linux_src
