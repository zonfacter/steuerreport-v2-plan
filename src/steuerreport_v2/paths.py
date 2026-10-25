from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(
    os.environ.get(
        "STEUERREPORT_V2_ROOT",
        Path(__file__).resolve().parents[2],
    )
).expanduser().resolve()

USERTRANSFER_ROOT = Path(
    os.environ.get(
        "STEUERREPORT_USERTRANSFER_ROOT",
        PROJECT_ROOT / "imports",
    )
).expanduser().resolve()


def resolve_project_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def resolve_usertransfer_path(path: str | Path) -> Path:
    # Late import avoids a cycle: private_settings also uses PROJECT_ROOT.
    from steuerreport_v2.private_settings import private_value

    candidate = Path(path).expanduser()
    root = Path(private_value("import_root") or USERTRANSFER_ROOT).expanduser()
    return candidate if candidate.is_absolute() else root / candidate


def configured_import_path(key: str, fallback: str = "") -> Path:
    from steuerreport_v2.private_settings import private_value

    return resolve_usertransfer_path(private_value(key) or fallback)
