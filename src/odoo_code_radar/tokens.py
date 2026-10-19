"""The saved token, for scans that run on a schedule without anyone at the keyboard.

It lives in one file in the user's own config folder, readable only by them. It is never written
anywhere else: not in odoo-code-radar.yml, not in the scheduler entry, not in logs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


class TokenFileError(RuntimeError):
    pass


def token_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "odoo-code-radar" / "token"


def load() -> str | None:
    path = token_path()
    if not path.exists():
        return None
    if sys.platform != "win32" and path.stat().st_mode & 0o077:
        raise TokenFileError(
            f"{path} can be read by other users, so it is not used. Fix it with: chmod 600 {path}"
        )
    token = path.read_text(encoding="utf-8").strip()
    return token or None


def save(token: str) -> Path:
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        path.parent.chmod(0o700)
    # Created with owner-only permissions from the start, so it is never readable by others.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token.strip() + "\n")
    if sys.platform != "win32":
        path.chmod(0o600)
    return path


def delete() -> bool:
    path = token_path()
    if path.exists():
        path.unlink()
        return True
    return False


def looks_like_token(value: str) -> bool:
    return len(value) >= 20 and not any(c.isspace() for c in value)
