"""A desktop pop-up after a scheduled scan finds something. Best effort: silent where unsupported."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def desktop(title: str, message: str) -> bool:
    try:
        if sys.platform == "darwin":
            script = f"display notification {_applescript(message)} with title {_applescript(title)}"
            return (
                subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10).returncode == 0
            )
        if sys.platform.startswith("linux") and shutil.which("notify-send"):
            if not any(os.environ.get(v) for v in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")):
                return False  # a headless server: nobody to show it to
            cmd = ["notify-send", "--app-name=odoo-code-radar", title, message]
            return subprocess.run(cmd, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    return False


def _applescript(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
