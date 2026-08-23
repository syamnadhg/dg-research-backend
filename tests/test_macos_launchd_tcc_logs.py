"""macOS launchd supervisor log paths must be TCC-safe (live incident 2026-07-19).

launchd opens a service's StandardOutPath/StandardErrorPath ITSELF before exec.
That open is attributed to launchd — not the target binary — so no user TCC
grant (not even Full Disk Access on the python interpreter) can allow it into a
protected folder (~/Downloads, ~/Desktop, ~/Documents, iCloud). With a source
checkout under ~/Downloads, the agent died at spawn-init with exit code 78
(EX_CONFIG), EMPTY logs, and a 10s respawn loop — the device never came online
after --pair even though pairing itself succeeded.

Fix: `_arm_supervisor_macos` writes supervisor logs somewhere launchd can
always open, and not inside the install — `script_dir/logs` sat in
site-packages, where an `--update` reinstall wiped them. The function also
WARNs when the checkout itself is under a TCC-protected folder (the
python-attributed reads there still need a one-time per-binary grant).

⚠ THE ASSERTION BELOW USED TO NAME ~/Library/Logs/SuperResearch, and that was a
literal standing in for a contract. It has moved to `_supervisor_log_dir()`
(2026-08-22, wave 5) because the old location met both constraints above and a
third nobody had checked: `--send-logs` collects `supervisor*.log` from the log
root, so a support bundle from a machine that never came online carried ZERO
bytes of the one file that says why. The properties are what this file pins now
— TCC-safe, outside the install, and collectable — which is strictly more than
the path was.

Run:  pytest tests/test_macos_launchd_tcc_logs.py -v
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import research


MAC_SRC = inspect.getsource(research._arm_supervisor_macos)


def test_macos_log_dir_is_one_launchd_can_open():
    """⛔⛔ THE CONSTRAINT, not a path. launchd's own open cannot enter a
    protected folder whatever the user grants."""
    assert "log_dir = _supervisor_log_dir()" in MAC_SRC
    # The old TCC-broken location must be gone.
    assert 'log_dir = script_dir / "logs"' not in MAC_SRC
    parts = research._supervisor_log_dir().parts
    for protected in ("Downloads", "Desktop", "Documents"):
        assert protected not in parts, f"{protected} is TCC-gated for launchd"


def test_macos_log_dir_is_outside_the_install():
    """`<install>/logs` is site-packages for a pipx build, and an `--update`
    reinstall deletes it — the evidence for the failure the update was meant
    to fix."""
    install = os.path.realpath(os.path.dirname(research.__file__))
    got = os.path.realpath(str(research._supervisor_log_dir()))
    assert not got.startswith(install + os.sep) and got != install


def test_macos_log_dir_is_one_the_support_bundle_collects():
    """⭐ THE PROPERTY THE OLD PATH DID NOT HAVE, and the reason it moved. A log
    launchd can open, that survives an update, and that no support call has ever
    seen is two thirds of a fix."""
    assert research._supervisor_log_dir() == research._logs_root()


def test_macos_plist_template_still_wires_log_dir():
    # The template must keep deriving both std paths from log_dir, so the
    # relocation actually reaches the plist. They now go through the XML escaper
    # first (every interpolated value derives from $HOME, and an `&` in a home
    # path writes a plist launchd cannot parse), so the derivation is asserted at
    # the escape site rather than inside the template.
    assert "out_log = _x(log_dir / 'supervisor.out.log')" in MAC_SRC
    assert "err_log = _x(log_dir / 'supervisor.err.log')" in MAC_SRC
    assert "<string>{out_log}</string>" in MAC_SRC
    assert "<string>{err_log}</string>" in MAC_SRC
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
