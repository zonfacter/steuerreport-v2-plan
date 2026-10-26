"""Private Connector-Authentifizierung; Aktivierung nur durch lokalen Bootstrap."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import stat

from steuerreport_v2.paths import PROJECT_ROOT
from steuerreport_v2.private_settings import private_state_root

TOKEN_FILE_ENV = "STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE"


def token_path() -> Path | None:
    configured = os.environ.get(TOKEN_FILE_ENV)
    if configured is not None:
        return Path(configured).expanduser() if configured.strip() else None
    return private_state_root() / "keys" / "connector-setup.token"


def _safe_managed_file(path: Path) -> bool:
    try:
        info = path.lstat()
        return stat.S_ISREG(info.st_mode) and not info.st_mode & 0o077 and info.st_nlink == 1 and _private_parents(path)
    except OSError:
        return False


def _private_parents(path: Path) -> bool:
    for parent in path.absolute().parents:
        info = parent.stat()
        if parent.is_symlink() or info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX:
            return False
    return True


def read_token() -> str:
    path = token_path()
    if path is None:
        return ""
    # Explizite Legacy-Pfade behalten ihre bisherige Lesesemantik. Kein Fallback
    # auf ein anderes Passwort bei falscher oder leerer Umgebungskonfiguration.
    if TOKEN_FILE_ENV not in os.environ and not _safe_managed_file(path):
        return ""
    try:
        if path.stat().st_size > 4096:
            return ""
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def initialize_token() -> dict:
    path = token_path()
    if path is None:
        raise RuntimeError("connector_setup_explicitly_disabled")
    if path.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        raise RuntimeError("connector_setup_file_inside_software")
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise RuntimeError("connector_setup_symlink_not_allowed")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not _private_parents(path):
        raise RuntimeError("connector_setup_directory_not_private")
    created = False
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        if not _safe_managed_file(path) or not read_token():
            raise RuntimeError("connector_setup_existing_file_unsafe_or_empty") from None
    else:
        created = True
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(secrets.token_urlsafe(48) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    return {"configured": True, "created": created, "file": str(path), "secret_returned": False}
