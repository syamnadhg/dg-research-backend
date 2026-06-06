"""`agent autostart` — keep the host bridge up across logon.

On Windows the always-up bridge is a **Scheduled Task** (`SuperAgentBridge`) that
runs ``python -m facade serve`` at logon, so a reboot brings the bridge back. The
account session + device selection already persist (keyring + prefs), so a bridge
restart resumes cleanly without re-login.

The schtasks argv is built by pure functions (unit-testable); only install/
uninstall/status actually shell out, and only on Windows.
"""

from __future__ import annotations

import subprocess
import sys

TASK_NAME = "SuperAgentBridge"


def is_windows() -> bool:
    return sys.platform.startswith("win")


def run_command() -> str:
    """The command the scheduled task runs (this interpreter + the serve entry)."""
    return f'"{sys.executable}" -m facade serve'


def install_argv(task_name: str = TASK_NAME) -> list[str]:
    # ONLOGON so it starts at sign-in; LIMITED run level (no elevation needed);
    # /F overwrites an existing task (idempotent re-install).
    return ["schtasks", "/Create", "/TN", task_name, "/TR", run_command(),
            "/SC", "ONLOGON", "/RL", "LIMITED", "/F"]


def uninstall_argv(task_name: str = TASK_NAME) -> list[str]:
    return ["schtasks", "/Delete", "/TN", task_name, "/F"]


def status_argv(task_name: str = TASK_NAME) -> list[str]:
    return ["schtasks", "/Query", "/TN", task_name]


def _exec(argv: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as e:  # pragma: no cover - env-specific
        return False, str(e)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()


def install(task_name: str = TASK_NAME) -> tuple[bool, str]:
    if not is_windows():
        return False, "autostart is Windows-only for now (use your OS service manager)"
    return _exec(install_argv(task_name))


def uninstall(task_name: str = TASK_NAME) -> tuple[bool, str]:
    if not is_windows():
        return False, "autostart is Windows-only for now"
    return _exec(uninstall_argv(task_name))


def status(task_name: str = TASK_NAME) -> tuple[bool, str]:
    if not is_windows():
        return False, "autostart is Windows-only for now"
    return _exec(status_argv(task_name))
